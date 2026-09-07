// VLAudioLoader - shared Wwise soundbank loader for JWE3 mods.
//
// JWE3 discovers soundbanks by walking <pack>/Audio/ over a list of content
// pack names hardcoded in the exe (Content0, ContentDeluxe, ContentPDLC1,
// ContentPDLCRebirth, ContentPDLC3 + Content_Localised_*). A mod folder is
// never walked, so a mod can never get a bank to the sound engine that way.
//
// This DLL makes the AK::SoundEngine::LoadBank call itself, using the Wwise
// API that JWE3.exe exports by name. It is deliberately ONE shared component
// rather than a per-mod copy: every mod that wants custom audio drops banks in
// its own folder and depends on this loader.
//
// Any mod's banks are picked up from:   Win64/ovldata/<AnyMod>/Audio/*.bnk
// Each bank must carry a unique Wwise bank ID and unique event names; see the
// namespacing rules in CLAUDE.md. This loader does not police that, it only
// reports the IDs it loaded so collisions are visible in the log.
//
// Called from Lua via package.loadlib. The lua_State* argument is ignored and
// no results are returned, so the unusable Lua C API never comes into it.

#include <windows.h>
#include <stdio.h>
#include <stdarg.h>

#define LOGPATH   "./VLAudioLoader.log"
#define NAMEFILE  "./VLPlay.txt"
#define OVLDATA   "./Win64/ovldata"
#define MAXBANKS  256

typedef int AKRESULT;
typedef unsigned int AkUInt32;
typedef AKRESULT (*PFN_LoadBankMemoryCopy)(const void*, AkUInt32, AkUInt32*);

static AkUInt32 g_loaded[MAXBANKS];
static int g_loaded_count = 0;

static void vlog(const char* fmt, ...) {
    FILE* f = fopen(LOGPATH, "a");
    if (!f) return;
    va_list ap;
    va_start(ap, fmt);
    vfprintf(f, fmt, ap);
    va_end(ap);
    fputc('\n', f);
    fclose(f);
}

static void* read_all(const char* path, DWORD* out_size) {
    HANDLE h = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, NULL,
                           OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) {
        vlog("    open FAILED (err %lu)", GetLastError());
        return NULL;
    }
    DWORD sz = GetFileSize(h, NULL);
    void* buf = VirtualAlloc(NULL, sz, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    DWORD got = 0;
    if (!buf || !ReadFile(h, buf, sz, &got, NULL) || got != sz) {
        vlog("    read FAILED (err %lu)", GetLastError());
        CloseHandle(h);
        return NULL;
    }
    CloseHandle(h);
    *out_size = sz;
    return buf;
}

// A real Wwise bank starts with a BKHD chunk; the bank ID is at offset 0x0C.
// Reject anything else early, so a cobra .bnk header stub (magic "BNK\0")
// never reaches the sound engine.
static int bank_header_ok(const unsigned char* d, DWORD sz, AkUInt32* out_id) {
    if (sz < 0x18) return 0;
    if (memcmp(d, "BKHD", 4) != 0) return 0;
    *out_id = *(const AkUInt32*)(d + 0x0C);
    return 1;
}

static int already_loaded(AkUInt32 id) {
    for (int i = 0; i < g_loaded_count; i++)
        if (g_loaded[i] == id) return 1;
    return 0;
}

static void load_one(PFN_LoadBankMemoryCopy pLoad, const char* mod, const char* path) {
    DWORD sz = 0;
    unsigned char* data = (unsigned char*)read_all(path, &sz);
    if (!data) return;

    AkUInt32 declared = 0;
    if (!bank_header_ok(data, sz, &declared)) {
        vlog("    SKIP not a BKHD bank (%lu bytes): %s", sz, path);
        return;
    }
    if (already_loaded(declared)) {
        vlog("    SKIP bank 0x%08X already loaded by this session", declared);
        return;
    }

    AkUInt32 bankID = 0;
    AKRESULT r = pLoad(data, sz, &bankID);
    vlog("    [%s] %s", mod, path);
    vlog("      %lu bytes, declared id 0x%08X -> AKRESULT=%d bankID=0x%08X",
         sz, declared, r, bankID);

    if (r == 1 && g_loaded_count < MAXBANKS)   // AK_Success
        g_loaded[g_loaded_count++] = bankID;
}

static void scan_mod(PFN_LoadBankMemoryCopy pLoad, const char* mod) {
    char pattern[MAX_PATH];
    snprintf(pattern, sizeof(pattern), "%s/%s/Audio/*.bnk", OVLDATA, mod);

    WIN32_FIND_DATAA fd;
    HANDLE h = FindFirstFileA(pattern, &fd);
    if (h == INVALID_HANDLE_VALUE) return;
    do {
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) continue;
        char full[MAX_PATH];
        snprintf(full, sizeof(full), "%s/%s/Audio/%s", OVLDATA, mod, fd.cFileName);
        load_one(pLoad, mod, full);
    } while (FindNextFileA(h, &fd));
    FindClose(h);
}

__declspec(dllexport) int fnVLLoadAllBanks(void* unused_lua_state) {
    (void)unused_lua_state;
    vlog("=== fnVLLoadAllBanks ===");

    // If two mods ship their own copy of this DLL, only one scans AT A TIME.
    // Held for the duration of the scan only - repeat calls must still work.
    // Build with /DVL_NO_MUTEX to bypass it (used when an older copy of this
    // DLL is already resident in the process and still owns the mutex).
    HANDLE once = NULL;
#ifndef VL_NO_MUTEX
    once = CreateMutexA(NULL, FALSE, "Global\\VLAudioLoader_scan");
    if (once && WaitForSingleObject(once, 0) != WAIT_OBJECT_0) {
        vlog("  another VLAudioLoader instance is mid-scan; standing down");
        CloseHandle(once);
        return 0;
    }
#endif

    HMODULE exe = GetModuleHandleW(NULL);
    PFN_LoadBankMemoryCopy pLoad = (PFN_LoadBankMemoryCopy)GetProcAddress(
        exe, "?LoadBankMemoryCopy@SoundEngine@AK@@YA?AW4AKRESULT@@PEBXIAEAI@Z");
    vlog("  exe=%p  LoadBankMemoryCopy=%p", (void*)exe, (void*)pLoad);
    if (!pLoad) {
        vlog("  ABORT: export not found");
        if (once) { ReleaseMutex(once); CloseHandle(once); }
        return 0;
    }

    WIN32_FIND_DATAA fd;
    char pattern[MAX_PATH];
    snprintf(pattern, sizeof(pattern), "%s/*", OVLDATA);
    HANDLE h = FindFirstFileA(pattern, &fd);
    if (h == INVALID_HANDLE_VALUE) {
        vlog("  ABORT: cannot list %s (err %lu)", OVLDATA, GetLastError());
        if (once) { ReleaseMutex(once); CloseHandle(once); }
        return 0;
    }
    int mods = 0;
    do {
        if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) continue;
        if (fd.cFileName[0] == '.') continue;
        // Stock packs are walked by the engine already - never touch them.
        if (strncmp(fd.cFileName, "Content", 7) == 0) continue;
        scan_mod(pLoad, fd.cFileName);
        mods++;
    } while (FindNextFileA(h, &fd));
    FindClose(h);

    vlog("  scanned %d mod folders, %d bank(s) loaded this session", mods, g_loaded_count);
    if (once) {
        ReleaseMutex(once);
        CloseHandle(once);
    }
    return 0;
}



// ---- fnVLPlayAt: post at a DISTANCE, to test attenuation -------------------
//
// fnVLPlay puts emitter and listener at the same point, where attenuation can
// never silence anything. That is why every hand-posted event was audible while
// the animal - a real emitter metres away - was silent. This posts at a chosen
// distance so the two cases can be compared.
//
// SetPosition kept returning 31, i.e. it was REJECTED, so the emitter never had
// a position at all. AkWorldTransform's layout differs between Wwise versions
// (older: front/top/position all float32 = 36 bytes; newer: float64 position =
// 48). Rather than guess again, try each and report which the engine accepts.
//
// VLPlay.txt: line 1 = event name, line 2 = distance in metres (default 0).

typedef unsigned long long AkGameObjectID;
typedef unsigned int AkUniqueID;
typedef AKRESULT (*PFN_SetPosition)(AkGameObjectID, const void*, int);
typedef AKRESULT (*PFN_SetListeners)(AkGameObjectID, const AkGameObjectID*, AkUInt32);
typedef AkUniqueID (*PFN_GetIDFromString2)(const char*);
typedef AKRESULT (*PFN_RegisterGameObj2)(AkGameObjectID);
typedef AkUniqueID (*PFN_PostEvent2)(AkUniqueID, AkGameObjectID, AkUInt32,
                                     void*, void*, AkUInt32, void*, AkUInt32);

static void fill36(unsigned char* b, float x, float y, float z) {
    memset(b, 0, 36);
    float* f = (float*)b;
    f[0]=0.f; f[1]=0.f; f[2]=1.f;      // front
    f[3]=0.f; f[4]=1.f; f[5]=0.f;      // top
    f[6]=x;   f[7]=y;   f[8]=z;        // position (float32)
}
static void fill48(unsigned char* b, double x, double y, double z) {
    memset(b, 0, 48);
    float* f = (float*)b;
    f[0]=0.f; f[1]=0.f; f[2]=1.f;
    f[3]=0.f; f[4]=1.f; f[5]=0.f;
    double* d = (double*)(b + 24);
    d[0]=x; d[1]=y; d[2]=z;            // position (float64)
}

__declspec(dllexport) int fnVLPlayAt(void* unused) {
    (void)unused;
    vlog("=== fnVLPlayAt ===");
    char name[256] = {0}; double dist = 0.0;
    FILE* f = fopen("./VLPlay.txt", "r");
    if (f) {
        if (fgets(name, sizeof(name), f)) {
            int n=(int)strlen(name);
            while (n>0 && (name[n-1]=='\n'||name[n-1]=='\r'||name[n-1]==' ')) name[--n]=0;
        }
        char dbuf[64];
        if (fgets(dbuf, sizeof(dbuf), f)) dist = atof(dbuf);
        fclose(f);
    }
    if (!name[0]) { vlog("  ABORT: no event name"); return 0; }

    HMODULE exe = GetModuleHandleW(NULL);
    PFN_GetIDFromString2 pHash = (PFN_GetIDFromString2)GetProcAddress(
        exe, "?GetIDFromString@SoundEngine@AK@@YAIPEBD@Z");
    PFN_RegisterGameObj2 pReg = (PFN_RegisterGameObj2)GetProcAddress(
        exe, "?RegisterGameObj@SoundEngine@AK@@YA?AW4AKRESULT@@_K@Z");
    PFN_SetPosition pPos = (PFN_SetPosition)GetProcAddress(
        exe, "?SetPosition@SoundEngine@AK@@YA?AW4AKRESULT@@_KAEBVAkWorldTransform@@W4AkSetPositionFlags@@@Z");
    PFN_SetListeners pLis = (PFN_SetListeners)GetProcAddress(
        exe, "?SetListeners@SoundEngine@AK@@YA?AW4AKRESULT@@_KPEB_KI@Z");
    PFN_PostEvent2 pPost = (PFN_PostEvent2)GetProcAddress(
        exe, "?PostEvent@SoundEngine@AK@@YAII_KIP6AXW4AkCallbackType@@PEAUAkCallbackInfo@@@ZPEAXIPEAUAkExternalSourceInfo@@I@Z");
    if (!pHash || !pReg || !pPost) { vlog("  ABORT: export missing"); return 0; }

    const AkGameObjectID EM = 0x564C0021ULL, LI = 0x564C0022ULL;
    pReg(EM); pReg(LI);

    unsigned char b36[36], b48[48];
    int ok36 = 0, ok48 = 0;
    if (pPos) {
        fill36(b36, 0.f, 0.f, 0.f);
        int r = pPos(LI, b36, 0);
        ok36 = (r == 1);
        vlog("  SetPosition(listener, 36-byte AkTransform) -> %d", r);
        if (!ok36) {
            fill48(b48, 0.0, 0.0, 0.0);
            r = pPos(LI, b48, 0);
            ok48 = (r == 1);
            vlog("  SetPosition(listener, 48-byte AkWorldTransform) -> %d", r);
        }
        if (ok36)      { fill36(b36, (float)dist, 0.f, 0.f); vlog("  emitter at %.1f m (36) -> %d", dist, pPos(EM, b36, 0)); }
        else if (ok48) { fill48(b48, dist, 0.0, 0.0);        vlog("  emitter at %.1f m (48) -> %d", dist, pPos(EM, b48, 0)); }
        else vlog("  WARNING: neither layout accepted; emitter has NO position");
    }
    if (pLis) { AkGameObjectID ls[1]; ls[0]=LI; pLis(EM, ls, 1); }

    AkUInt32 id = pHash(name);
    AkUInt32 playing = pPost(id, EM, 0, NULL, NULL, 0, NULL, 0);
    vlog("  PostEvent('%s' 0x%08X) at %.1f m -> playingID=%u %s",
         name, id, dist, playing, playing ? "RESOLVED" : "FAILED");
    return 0;
}
