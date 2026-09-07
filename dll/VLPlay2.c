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


// ---- fnVLPlay: the PLAYBACK test ------------------------------------------
//
// The earlier diag posted an event on a game object that had NO POSITION and
// NO LISTENER. Wwise happily returns a non-zero playingID for that - the event
// resolved - and then renders nothing audible. That is almost certainly why
// "it loaded but I heard nothing" kept happening.
//
// So this registers BOTH an emitter and its own listener, puts them at the same
// point, and wires the listener to the emitter. Distance 0 means attenuation
// cannot silence it, and we do not need to know where the game's camera is.
//
// The event name is read from ./VLPlay.txt at call time, so a different event
// can be tried without rebuilding the DLL (the Lua sandbox has no io library,
// so the file is written from outside the game).

typedef unsigned long long AkGameObjectID;
typedef unsigned int AkUniqueID;

typedef AkUniqueID (*PFN_GetIDFromString)(const char*);
typedef AKRESULT   (*PFN_RegisterGameObj)(AkGameObjectID);
typedef AKRESULT   (*PFN_SetPosition)(AkGameObjectID, const void*, int);
typedef AKRESULT   (*PFN_SetListeners)(AkGameObjectID, const AkGameObjectID*, AkUInt32);
typedef AkUniqueID (*PFN_PostEvent)(AkUniqueID, AkGameObjectID, AkUInt32,
                                    void*, void*, AkUInt32, void*, AkUInt32);

// AkWorldTransform is {front[3] f32, top[3] f32, position[3] f64} = 48 bytes in
// current Wwise; the older AkTransform is {front, top, position} all f32 = 36.
// A 48-byte buffer that is zero everywhere except front=(0,0,1) at offset 0 and
// top=(0,1,0) at offset 12 is VALID UNDER BOTH layouts - position reads as the
// origin either way - so we do not have to know which one this build uses.
static void make_transform(unsigned char* buf48) {
    memset(buf48, 0, 48);
    float* f = (float*)buf48;
    f[0] = 0.0f; f[1] = 0.0f; f[2] = 1.0f;   // orientationFront = +Z
    f[3] = 0.0f; f[4] = 1.0f; f[5] = 0.0f;   // orientationTop   = +Y
}

static void read_event_name(char* out, int cap) {
    out[0] = 0;
    FILE* f = fopen(NAMEFILE, "r");
    if (!f) return;
    if (fgets(out, cap, f)) {
        int n = (int)strlen(out);
        while (n > 0 && (out[n-1] == '\n' || out[n-1] == '\r' || out[n-1] == ' ')) out[--n] = 0;
    }
    fclose(f);
}

__declspec(dllexport) int fnVLPlay(void* unused_lua_state) {
    (void)unused_lua_state;
    vlog("=== fnVLPlay ===");

    char name[256];
    read_event_name(name, sizeof(name));
    if (!name[0]) { vlog("  ABORT: %s missing or empty", NAMEFILE); return 0; }

    HMODULE exe = GetModuleHandleW(NULL);
    PFN_GetIDFromString pHash = (PFN_GetIDFromString)GetProcAddress(
        exe, "?GetIDFromString@SoundEngine@AK@@YAIPEBD@Z");
    PFN_RegisterGameObj pReg = (PFN_RegisterGameObj)GetProcAddress(
        exe, "?RegisterGameObj@SoundEngine@AK@@YA?AW4AKRESULT@@_K@Z");
    PFN_SetPosition pPos = (PFN_SetPosition)GetProcAddress(
        exe, "?SetPosition@SoundEngine@AK@@YA?AW4AKRESULT@@_KAEBVAkWorldTransform@@W4AkSetPositionFlags@@@Z");
    PFN_SetListeners pLis = (PFN_SetListeners)GetProcAddress(
        exe, "?SetListeners@SoundEngine@AK@@YA?AW4AKRESULT@@_KPEB_KI@Z");
    PFN_PostEvent pPost = (PFN_PostEvent)GetProcAddress(
        exe, "?PostEvent@SoundEngine@AK@@YAII_KIP6AXW4AkCallbackType@@PEAUAkCallbackInfo@@@ZPEAXIPEAUAkExternalSourceInfo@@I@Z");

    vlog("  hash=%p reg=%p setpos=%p setlis=%p post=%p",
         (void*)pHash, (void*)pReg, (void*)pPos, (void*)pLis, (void*)pPost);
    if (!pHash || !pReg || !pPost) { vlog("  ABORT: required export missing"); return 0; }

    const AkGameObjectID EMITTER  = 0x564C0011ULL;
    const AkGameObjectID LISTENER = 0x564C0012ULL;

    vlog("  RegisterGameObj(emitter)  -> %d", pReg(EMITTER));
    vlog("  RegisterGameObj(listener) -> %d", pReg(LISTENER));

    unsigned char xf[48];
    make_transform(xf);
    if (pPos) {
        vlog("  SetPosition(emitter)  -> %d", pPos(EMITTER,  xf, 0));
        vlog("  SetPosition(listener) -> %d", pPos(LISTENER, xf, 0));
    } else {
        vlog("  WARNING: SetPosition export missing - emitter has no position");
    }
    if (pLis) {
        AkGameObjectID ls[1]; ls[0] = LISTENER;
        vlog("  SetListeners(emitter <- listener) -> %d", pLis(EMITTER, ls, 1));
    } else {
        vlog("  WARNING: SetListeners export missing - emitter has no listener");
    }

    AkUInt32 id = pHash(name);
    AkUInt32 playing = pPost(id, EMITTER, 0, NULL, NULL, 0, NULL, 0);
    vlog("  PostEvent('%s' 0x%08X) -> playingID=%u %s",
         name, id, playing, playing ? "RESOLVED" : "FAILED-TO-RESOLVE");
    vlog("  (playingID != 0 only means Wwise accepted it; LISTEN to confirm audio)");
    return 0;
}

// ---- fnVLUnload: free the colliding stock bank, then load ours -------------
// Our re-ID'd bank re-hashed only its 228 EVENT ids; its ~839 sounds,
// containers and actor-mixers still carry the donor's original ids. The stock
// Deinosuchus_events bank is already resident with those objects parented, so
// LoadBankMemoryCopy rejects ours with AK_ChildAlreadyHasAParent (21).
// Unloading the stock bank first removes the collision WITHOUT needing a full
// 1067-object remap - enough to answer "can a mod-folder bank make sound?".
// The stock bank comes back on the next game start; nothing on disk changes.
typedef AKRESULT (*PFN_UnloadBankID)(AkUInt32, const void*, AkUInt32);

__declspec(dllexport) int fnVLUnload(void* unused_lua_state) {
    (void)unused_lua_state;
    vlog("=== fnVLUnload ===");
    HMODULE exe = GetModuleHandleW(NULL);
    PFN_UnloadBankID pUnload = (PFN_UnloadBankID)GetProcAddress(
        exe, "?UnloadBank@SoundEngine@AK@@YA?AW4AKRESULT@@IPEBXI@Z");
    vlog("  UnloadBank=%p", (void*)pUnload);
    if (!pUnload) { vlog("  ABORT: export not found"); return 0; }
    AkUInt32 id = 0x9E5E4D2CU;   // fnv1("deinosuchus_events"), filled in below
    char buf[64];
    FILE* f = fopen("./VLUnload.txt", "r");
    if (f) { if (fgets(buf, sizeof(buf), f)) id = (AkUInt32)strtoul(buf, NULL, 16); fclose(f); }
    AKRESULT r = pUnload(id, NULL, 0);
    vlog("  UnloadBank(0x%08X) -> AKRESULT=%d  (1=success, 15=IDNotFound)", id, r);
    return 0;
}
