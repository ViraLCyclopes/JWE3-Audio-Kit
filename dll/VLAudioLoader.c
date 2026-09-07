// Optional legacy Lua entry point. With the proxy installed, it alone owns
// loading. A second independent scan would duplicate Wwise bank references.
#include "VLAudioRuntime.h"
__declspec(dllexport) int fnVLLoadAllBanks(void* lua) {
    HMODULE proxy = GetModuleHandleW(L"xinput1_4.dll");
    wchar_t path[VL_PATH], expected[VL_PATH];
    (void)lua;
    if (proxy && GetModuleFileNameW(proxy,path,VL_PATH) &&
        vl_game_path(expected,L"xinput1_4.dll") && !_wcsicmp(path,expected)) {
        vlog("fnVLLoadAllBanks: root XInput proxy owns automatic loading; no duplicate scan.");
        return 0;
    }
    // Standalone use is explicit, serialized per process, and validates the same
    // manifest. It is not needed in the standard installation.
    {
        static SRWLOCK lock = SRWLOCK_INIT;
        static int ran;
        AcquireSRWLockExclusive(&lock);
        if (!ran && vl_prepare()) { vl_load_all(0); ran = 1; }
        ReleaseSRWLockExclusive(&lock);
    }
    return 0;
}
__declspec(dllexport) int fnVLDiag(void* lua) {
    (void)lua;
    vlog("VLAudioLoader v6 diagnostics: inspect manifest validation and bank AKRESULT lines in this log. Manual PostEvent does not prove creature-driven playback.");
    return 0;
}
BOOL WINAPI DllMain(HINSTANCE instance,DWORD reason,LPVOID reserved) {
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) DisableThreadLibraryCalls(instance);
    return TRUE;
}
