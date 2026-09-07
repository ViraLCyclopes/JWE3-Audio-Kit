// Shared production loader. The proxy and optional Lua entry point use one
// validation/load implementation; diagnostic DLLs are not production dependencies.
#ifndef VL_AUDIO_RUNTIME_H
#define VL_AUDIO_RUNTIME_H
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <bcrypt.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#include <wchar.h>
#pragma comment(lib, "bcrypt.lib")

#define VL_PATH 32768
#define VL_REL 1024
typedef struct VLFile {
    wchar_t rel[VL_REL];
    unsigned char hash[32];
    unsigned int bank;
    int is_bank, matched, loaded;
} VLFile;
static wchar_t vl_root[VL_PATH];
static VLFile* vl_files;
static size_t vl_count, vl_capacity;
static volatile LONG vl_audio_seen;
static int vl_valid;
static INIT_ONCE vl_paths_once = INIT_ONCE_STATIC_INIT;

static BOOL CALLBACK vl_paths(PINIT_ONCE once, PVOID arg, PVOID* ctx) {
    DWORD n;
    wchar_t* slash;
    (void)once; (void)arg; (void)ctx;
    n = GetModuleFileNameW(NULL, vl_root, VL_PATH);
    if (!n || n >= VL_PATH) return FALSE;
    slash = wcsrchr(vl_root, L'\\');
    if (!slash) return FALSE;
    *slash = 0;
    return TRUE;
}
static int vl_game_path(wchar_t* out, const wchar_t* rel) {
    if (!InitOnceExecuteOnce(&vl_paths_once, vl_paths, NULL, NULL)) return 0;
    return _snwprintf_s(out, VL_PATH, _TRUNCATE, L"%s\\%s", vl_root, rel) >= 0;
}
static int vl_data_path(wchar_t* out, const wchar_t* rel) {
    if (!InitOnceExecuteOnce(&vl_paths_once, vl_paths, NULL, NULL)) return 0;
    return _snwprintf_s(out, VL_PATH, _TRUNCATE, L"%s\\Win64\\ovldata\\%s", vl_root, rel) >= 0;
}
static void vlog(const char* fmt, ...) {
    // May be reached on a game thread: never reserve a 64 KiB stack buffer.
    wchar_t* path;
    FILE* f;
    va_list ap;
    DWORD error = GetLastError();
    path = (wchar_t*)malloc(VL_PATH * sizeof(wchar_t));
    if (!path) { SetLastError(error); return; }
    if (!vl_game_path(path, L"VLAudioLoader.log")) { free(path); SetLastError(error); return; }
    if (_wfopen_s(&f, path, L"a")) f = NULL;
    if (f) {
        va_start(ap, fmt); vfprintf(f, fmt, ap); va_end(ap);
        fputc('\n', f); fclose(f);
    }
    free(path);
    SetLastError(error);
}

static int vl_digest(const wchar_t* path, unsigned char out[32]) {
    BCRYPT_ALG_HANDLE alg = NULL;
    BCRYPT_HASH_HANDLE hash = NULL;
    HANDLE file = INVALID_HANDLE_VALUE;
    unsigned char buffer[65536];
    DWORD got;
    int ok = 0;
    if (BCryptOpenAlgorithmProvider(&alg, BCRYPT_SHA256_ALGORITHM, NULL, 0) < 0) goto end;
    if (BCryptCreateHash(alg, &hash, NULL, 0, NULL, 0, 0) < 0) goto end;
    file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (file == INVALID_HANDLE_VALUE) goto end;
    for (;;) {
        if (!ReadFile(file, buffer, sizeof(buffer), &got, NULL)) goto end;
        if (!got) break;
        if (BCryptHashData(hash, buffer, got, 0) < 0) goto end;
    }
    ok = BCryptFinishHash(hash, out, 32, 0) >= 0;
end:
    if (file != INVALID_HANDLE_VALUE) CloseHandle(file);
    if (hash) BCryptDestroyHash(hash);
    if (alg) BCryptCloseAlgorithmProvider(alg, 0);
    return ok;
}
static int vl_suffix(const wchar_t* name, const wchar_t* suffix) {
    size_t n = wcslen(name), s = wcslen(suffix);
    return n >= s && !_wcsicmp(name + n - s, suffix);
}
static int vl_buffer_matches(const void* data, DWORD size, const unsigned char expected[32]) {
    BCRYPT_ALG_HANDLE alg = NULL;
    BCRYPT_HASH_HANDLE hash = NULL;
    unsigned char actual[32];
    int ok = 0;
    if (BCryptOpenAlgorithmProvider(&alg,BCRYPT_SHA256_ALGORITHM,NULL,0) < 0) goto end;
    if (BCryptCreateHash(alg,&hash,NULL,0,NULL,0,0) < 0) goto end;
    if (BCryptHashData(hash,(PUCHAR)data,size,0) < 0) goto end;
    if (BCryptFinishHash(hash,actual,32,0) < 0) goto end;
    ok = memcmp(actual,expected,32) == 0;
end:
    if (hash) BCryptDestroyHash(hash);
    if (alg) BCryptCloseAlgorithmProvider(alg,0);
    return ok;
}
static int vl_add(const wchar_t* rel, int bank) {
    VLFile* next;
    if (wcslen(rel) >= VL_REL) { vlog("Audio path too long: %ls", rel); return 0; }
    if (vl_count == vl_capacity) {
        size_t cap = vl_capacity ? vl_capacity * 2 : 32;
        next = (VLFile*)realloc(vl_files, cap * sizeof(VLFile));
        if (!next) return 0;
        vl_files = next; vl_capacity = cap;
    }
    memset(&vl_files[vl_count], 0, sizeof(VLFile));
    wcscpy_s(vl_files[vl_count].rel, VL_REL, rel);
    vl_files[vl_count++].is_bank = bank;
    return 1;
}
static int vl_inventory(void) {
    wchar_t path[VL_PATH], rel[VL_REL];
    WIN32_FIND_DATAW mod, audio;
    HANDLE hm, ha;
    int ok = 1;
    vl_count = 0;
    if (!vl_add(L"Content0/Audio/MetaData/audiometadata.ovl", 0) ||
        !vl_add(L"VLAudioLoader/Audio/audiometadata.ovl", 0)) return 0;
    if (!vl_data_path(path, L"*")) return 0;
    hm = FindFirstFileW(path, &mod);
    if (hm == INVALID_HANDLE_VALUE) return 0;
    do {
        if (!(mod.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) || mod.cFileName[0] == L'.' ||
            !_wcsnicmp(mod.cFileName, L"Content", 7)) continue;
        if (_snwprintf_s(rel, VL_REL, _TRUNCATE, L"%s/Audio/*", mod.cFileName) < 0 ||
            !vl_data_path(path, rel)) { ok = 0; break; }
        ha = FindFirstFileW(path, &audio);
        if (ha == INVALID_HANDLE_VALUE) {
            DWORD error = GetLastError();
            if (error != ERROR_FILE_NOT_FOUND && error != ERROR_PATH_NOT_FOUND) { ok = 0; break; }
            continue;
        }
        do {
            int bank;
            if (audio.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) continue;
            bank = vl_suffix(audio.cFileName, L".bnk");
            if (!bank && !vl_suffix(audio.cFileName, L".wmetasb.add")) continue;
            if (_snwprintf_s(rel, VL_REL, _TRUNCATE, L"%s/Audio/%s", mod.cFileName, audio.cFileName) < 0 ||
                !vl_add(rel, bank)) { ok = 0; break; }
        } while (FindNextFileW(ha, &audio));
        if (ok && GetLastError() != ERROR_NO_MORE_FILES) ok = 0;
        FindClose(ha);
        if (!ok) break;
    } while (FindNextFileW(hm, &mod));
    if (ok && GetLastError() != ERROR_NO_MORE_FILES) ok = 0;
    FindClose(hm);
    return ok;
}
static int vl_hex(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return -1;
}
static int vl_manifest(void) {
    wchar_t path[VL_PATH], rel[VL_REL];
    char line[4096];
    FILE* f;
    size_t rows = 0, i;
    int ok = 1;
    if (!vl_data_path(path, L"VLAudioLoader/Audio/audio_manifest.sha256")) return 0;
    if (_wfopen_s(&f, path, L"rb")) f = NULL;
    if (!f) { vlog("Audio manifest missing; run merge_registry.bat with this loader version."); return 0; }
    if (!fgets(line, sizeof(line), f) || strcmp(line, "VLAUDIO1\n")) ok = 0;
    while (ok && fgets(line, sizeof(line), f)) {
        size_t length = strlen(line);
        unsigned char expected[32];
        if (length < 67 || line[64] != '\t' || line[length - 1] != '\n') { ok = 0; break; }
        line[length - 1] = 0;
        for (i = 0; i < 32; i++) {
            int a = vl_hex(line[i * 2]), b = vl_hex(line[i * 2 + 1]);
            if (a < 0 || b < 0) { ok = 0; break; }
            expected[i] = (unsigned char)((a << 4) | b);
        }
        if (!ok || !MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, line + 65, -1, rel, VL_REL)) { ok = 0; break; }
        // Match only discovered relative paths: a manifest cannot name arbitrary files.
        for (i = 0; i < vl_count; i++) if (!_wcsicmp(rel, vl_files[i].rel)) break;
        if (i == vl_count || vl_files[i].matched) { ok = 0; break; }
        vl_files[i].matched = 1;
        if (!vl_data_path(path, rel) || !vl_digest(path, vl_files[i].hash) ||
            memcmp(expected, vl_files[i].hash, 32)) {
            vlog("Audio content changed/missing: %ls", rel); ok = 0; break;
        }
        rows++;
    }
    if (ferror(f)) ok = 0;
    fclose(f);
    if (rows != vl_count) ok = 0;
    if (!ok) vlog("Audio manifest mismatch: install/remove/update detected. Run merge_registry.bat; using stock registry.");
    return ok;
}
static int vl_prepare(void) {
    vl_valid = vl_inventory() && vl_manifest();
    if (vl_valid) vlog("Audio manifest verified (%zu files, SHA-256).", vl_count);
    else vlog("Custom banks disabled until a valid registry merge is installed.");
    return vl_valid;
}

typedef int (*VLLoadBank)(const void*, unsigned int, unsigned int*);
typedef unsigned char (*VLIsInitialized)(void);
static void* vl_read(const wchar_t* rel, DWORD* size) {
    wchar_t path[VL_PATH];
    HANDLE file;
    LARGE_INTEGER length;
    DWORD got;
    void* data = NULL;
    if (!vl_data_path(path, rel)) return NULL;
    file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (file == INVALID_HANDLE_VALUE) return NULL;
    if (!GetFileSizeEx(file, &length) || length.QuadPart < 24 || length.QuadPart > MAXDWORD) goto end;
    *size = (DWORD)length.QuadPart;
    data = VirtualAlloc(NULL, *size, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    if (data && (!ReadFile(file, data, *size, &got, NULL) || got != *size)) {
        VirtualFree(data, 0, MEM_RELEASE); data = NULL;
    }
end:
    CloseHandle(file);
    return data;
}
static int vl_bank_order(const void* a, const void* b) {
    const VLFile *x = (const VLFile*)a, *y = (const VLFile*)b;
    int xm = vl_suffix(x->rel, L"_media.bnk"), ym = vl_suffix(y->rel, L"_media.bnk");
    if (xm != ym) return ym - xm;
    return _wcsicmp(x->rel, y->rel);
}
static int vl_bank_header(const unsigned char* data, DWORD size, unsigned int* bank) {
    size_t at = 0;
    if (size < 24 || memcmp(data, "BKHD", 4)) return 0;
    while (at + 8 <= size) {
        unsigned int length;
        memcpy(&length, data + at + 4, 4);
        if (length > size - at - 8) return 0;
        at += 8 + length;
    }
    if (at != size) return 0;
    memcpy(bank, data + 12, 4);
    return *bank != 0;
}
static int vl_load_banks(VLLoadBank load, VLIsInitialized ready, int require_activity) {
    size_t i, j;
    int pass, loaded = 0, waiting;
    if (!load || !ready) { vlog("Required Wwise exports missing; custom loader disabled."); return 0; }
    for (waiting = 0; waiting < 1200; waiting++) {
        if (ready() && (!require_activity || InterlockedCompareExchange(&vl_audio_seen, 0, 0))) break;
        Sleep(100);
    }
    if (waiting == 1200) { vlog("Audio initialization/activity timeout; custom loader disabled."); return 0; }
    qsort(vl_files, vl_count, sizeof(VLFile), vl_bank_order);
    // Preflight every bank before loading any; never let enumeration order choose
    // a conflicting ID. Input hashes were already checked against the manifest.
    for (i = 0; i < vl_count; i++) if (vl_files[i].is_bank) {
        DWORD size = 0;
        unsigned char* data = (unsigned char*)vl_read(vl_files[i].rel, &size);
        int ok = data && vl_bank_header(data, size, &vl_files[i].bank) && vl_buffer_matches(data,size,vl_files[i].hash);
        if (data) VirtualFree(data, 0, MEM_RELEASE);
        if (!ok) { vlog("Invalid/unreadable bank: %ls", vl_files[i].rel); return 0; }
        for (j = 0; j < i; j++) if (vl_files[j].is_bank && vl_files[j].bank == vl_files[i].bank) {
            if (memcmp(vl_files[j].hash, vl_files[i].hash, 32)) {
                vlog("Bank ID conflict: %ls / %ls", vl_files[j].rel, vl_files[i].rel); return 0;
            }
        }
    }
    // Initialization-bank dependencies can still be pending after SoundEngine Init.
    // Retry failed banks a bounded number of times; successful banks are never reloaded.
    for (pass = 0; pass < 6; pass++) {
        int pending = 0;
        if (!ready()) { vlog("Sound engine shut down; stopping custom loader."); break; }
        for (i = 0; i < vl_count; i++) if (vl_files[i].is_bank && !vl_files[i].loaded) {
            DWORD size = 0;
            unsigned int bank = 0;
            unsigned char* data;
            int result, duplicate = 0;
            for (j = 0; j < vl_count; j++) if (vl_files[j].loaded && vl_files[j].bank == vl_files[i].bank) { duplicate = 1; break; }
            if (duplicate) { vl_files[i].loaded = 1; continue; }
            data = (unsigned char*)vl_read(vl_files[i].rel, &size);
            if (!data) { pending++; continue; }
            if (!vl_buffer_matches(data,size,vl_files[i].hash)) {
                VirtualFree(data,0,MEM_RELEASE);
                vlog("Bank changed after validation: %ls; stopping loader.",vl_files[i].rel);
                return loaded;
            }
            result = load(data, size, &bank);
            VirtualFree(data, 0, MEM_RELEASE); // synchronous memory-copy API owns its own allocation
            vlog("Bank %ls: AKRESULT=%d id=0x%08X attempt=%d", vl_files[i].rel, result, bank, pass + 1);
            if (result == 1 && bank == vl_files[i].bank) { vl_files[i].loaded = 1; loaded++; }
            else pending++;
        }
        if (!pending) break;
        if (pass < 5) Sleep(1000);
    }
    vlog("%d unique custom bank(s) loaded automatically.", loaded);
    return loaded;
}
static int vl_load_all(int require_activity) {
    HMODULE exe = GetModuleHandleW(NULL);
    VLLoadBank load = (VLLoadBank)GetProcAddress(exe,"?LoadBankMemoryCopy@SoundEngine@AK@@YA?AW4AKRESULT@@PEBXIAEAI@Z");
    VLIsInitialized ready = (VLIsInitialized)GetProcAddress(exe,"?IsInitialized@SoundEngine@AK@@YA_NXZ");
    return vl_load_banks(load,ready,require_activity);
}
#endif
