// VLPostSpy - logs every AK::SoundEngine::PostEvent the game makes, with the
// game object it was posted on.
//
// Why this exists: GetIDFromString is called ONLY when a motiongraph loads, never
// when an event is posted. So the hash spy could only ever show what a graph
// CONTAINS, not what the game FIRES. Every "the animal posts X" conclusion drawn
// from it was unsupported. This sees actual posts.
//
// Why a hardware breakpoint instead of an inline hook: PostEvent cannot be
// reimplemented the way GetIDFromString could (it is not a pure function), so
// observing it needs a real hook. Patching its prologue requires instruction
// length decoding, which is exactly what crashes naive hooks. A debug register
// plus a vectored exception handler patches NO code at all - the CPU traps on
// execution, we read the arguments out of the thread context, and resume.
//
// x64 calling convention: PostEvent(AkUniqueID eventID /*ECX*/,
//                                   AkGameObjectID gameObj /*RDX*/, ...)
// so the event id is in RCX (low 32) and the game object id is in RDX.

#include <windows.h>
#include <tlhelp32.h>
#include <stdio.h>
#include <stdarg.h>

#define LOGPATH "./VLPostSpy.log"
#define MAXLOG  400

static void* g_target;
static PVOID g_veh;
static volatile LONG g_logged;
static int  g_installed;

static void vlog(const char* fmt, ...) {
    FILE* f = fopen(LOGPATH, "a");
    if (!f) return;
    va_list ap; va_start(ap, fmt);
    vfprintf(f, fmt, ap); va_end(ap);
    fputc('\n', f); fclose(f);
}

static LONG CALLBACK veh(PEXCEPTION_POINTERS ep) {
    if (ep->ExceptionRecord->ExceptionCode != EXCEPTION_SINGLE_STEP)
        return EXCEPTION_CONTINUE_SEARCH;
    if ((void*)ep->ContextRecord->Rip != g_target)
        return EXCEPTION_CONTINUE_SEARCH;

    if (InterlockedIncrement(&g_logged) <= MAXLOG) {
        unsigned int  ev  = (unsigned int)(ep->ContextRecord->Rcx & 0xFFFFFFFF);
        unsigned long long go = ep->ContextRecord->Rdx;
        vlog("  PostEvent id=0x%08X  gameObject=0x%016llX", ev, go);
    }
    // Resume Flag: re-execute the trapped instruction without re-triggering.
    ep->ContextRecord->EFlags |= 0x10000;
    return EXCEPTION_CONTINUE_EXECUTION;
}

// Debug registers are PER THREAD, so the breakpoint must be armed on each one.
static int arm_threads(void* addr, int enable) {
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
    if (snap == INVALID_HANDLE_VALUE) return 0;
    THREADENTRY32 te; te.dwSize = sizeof(te);
    DWORD me = GetCurrentProcessId(), self = GetCurrentThreadId();
    int n = 0;
    if (Thread32First(snap, &te)) {
        do {
            if (te.th32OwnerProcessID != me) continue;
            if (te.th32ThreadID == self) continue;
            HANDLE h = OpenThread(THREAD_GET_CONTEXT | THREAD_SET_CONTEXT |
                                  THREAD_SUSPEND_RESUME, FALSE, te.th32ThreadID);
            if (!h) continue;
            CONTEXT c; c.ContextFlags = CONTEXT_DEBUG_REGISTERS;
            SuspendThread(h);
            if (GetThreadContext(h, &c)) {
                if (enable) {
                    c.Dr0 = (DWORD64)addr;
                    c.Dr7 &= ~(0xFULL << 16);   // DR0: execute, length 1
                    c.Dr7 |= 1ULL;              // L0
                } else {
                    c.Dr0 = 0;
                    c.Dr7 &= ~1ULL;
                }
                if (SetThreadContext(h, &c)) n++;
            }
            ResumeThread(h);
            CloseHandle(h);
        } while (Thread32Next(snap, &te));
    }
    CloseHandle(snap);
    return n;
}

__declspec(dllexport) int fnVLPostSpyStart(void* unused) {
    (void)unused;
    vlog("=== fnVLPostSpyStart ===");
    if (g_installed) { vlog("  already installed"); return 0; }

    HMODULE exe = GetModuleHandleW(NULL);
    g_target = (void*)GetProcAddress(exe,
        "?PostEvent@SoundEngine@AK@@YAII_KIP6AXW4AkCallbackType@@PEAUAkCallbackInfo@@@ZPEAXIPEAUAkExternalSourceInfo@@I@Z");
    if (!g_target) { vlog("  ABORT: PostEvent export not found"); return 0; }
    vlog("  PostEvent at %p", g_target);

    g_veh = AddVectoredExceptionHandler(1, veh);
    if (!g_veh) { vlog("  ABORT: AddVectoredExceptionHandler failed"); return 0; }

    int n = arm_threads(g_target, 1);
    g_installed = 1;
    vlog("  armed on %d threads - NOW MAKE THE ANIMAL VOCALISE", n);
    return 0;
}

// Re-arm: threads created after the initial sweep have clean debug registers.
__declspec(dllexport) int fnVLPostSpyRearm(void* unused) {
    (void)unused;
    if (!g_installed) { vlog("  not installed"); return 0; }
    vlog("  re-armed on %d threads", arm_threads(g_target, 1));
    return 0;
}

__declspec(dllexport) int fnVLPostSpyStop(void* unused) {
    (void)unused;
    vlog("=== fnVLPostSpyStop ===");
    if (!g_installed) return 0;
    arm_threads(g_target, 0);
    if (g_veh) RemoveVectoredExceptionHandler(g_veh);
    g_veh = NULL; g_installed = 0;
    vlog("  removed; %ld posts seen", g_logged);
    return 0;
}

BOOL WINAPI DllMain(HINSTANCE h, DWORD r, LPVOID x) {
    (void)h; (void)x;
    if (r == DLL_PROCESS_ATTACH) vlog("--- VLPostSpy attached ---");
    return TRUE;
}
