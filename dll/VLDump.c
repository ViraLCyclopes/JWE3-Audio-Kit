// VLDump - copy a range of the running exe's memory to a file.
//
// The on-disk JWE3.exe is Denuvo-protected, so code read from the file at a
// given RVA is not necessarily what actually executes. Dumping from the LIVE
// process gives the real instructions to disassemble.
//
// Range is read from ./VLDump.txt as two hex numbers: "<rva> <length>".

#include <windows.h>
#include <stdio.h>
#include <stdarg.h>

#define LOGPATH "./VLDump.log"

static void vlog(const char* fmt, ...) {
    FILE* f = fopen(LOGPATH, "a");
    if (!f) return;
    va_list ap; va_start(ap, fmt);
    vfprintf(f, fmt, ap); va_end(ap);
    fputc('\n', f); fclose(f);
}

__declspec(dllexport) int fnVLDump(void* unused) {
    (void)unused;
    unsigned long long rva = 0, len = 0;
    FILE* cfg = fopen("./VLDump.txt", "r");
    if (cfg) { fscanf(cfg, "%llx %llx", &rva, &len); fclose(cfg); }
    if (!rva || !len || len > (1u << 20)) {
        vlog("=== fnVLDump: bad range (rva=0x%llX len=0x%llX)", rva, len);
        return 0;
    }

    unsigned char* base = (unsigned char*)GetModuleHandleW(NULL);
    unsigned char* src  = base + rva;

    // Never fault the game: confirm the range is committed and readable first.
    MEMORY_BASIC_INFORMATION mbi;
    if (!VirtualQuery(src, &mbi, sizeof(mbi)) || mbi.State != MEM_COMMIT) {
        vlog("=== fnVLDump: exe+0x%llX is not committed", rva);
        return 0;
    }

    FILE* out = fopen("./VLDump.bin", "wb");
    if (!out) { vlog("=== fnVLDump: cannot open VLDump.bin"); return 0; }
    size_t wrote = fwrite(src, 1, (size_t)len, out);
    fclose(out);
    vlog("=== fnVLDump: wrote %zu bytes from exe+0x%llX (base %p)", wrote, rva, base);
    return 0;
}

BOOL WINAPI DllMain(HINSTANCE h, DWORD r, LPVOID x) {
    (void)h; (void)x; (void)r;
    return TRUE;
}
