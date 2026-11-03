"""Private resource-limited launcher. No network/provider credentials are needed."""

import os
import subprocess
import sys


def windows_limits(memory, cpu):
    import ctypes as ct
    from ctypes import wintypes as wt

    class Basic(ct.Structure):
        _fields_ = [
            ("process_time", ct.c_int64),
            ("job_time", ct.c_int64),
            ("flags", wt.DWORD),
            ("min_working_set", ct.c_size_t),
            ("max_working_set", ct.c_size_t),
            ("active_processes", wt.DWORD),
            ("affinity", ct.c_size_t),
            ("priority", wt.DWORD),
            ("scheduling", wt.DWORD),
        ]

    class Io(ct.Structure):
        _fields_ = [
            (name, ct.c_uint64)
            for name in (
                "read_ops",
                "write_ops",
                "other_ops",
                "read_bytes",
                "write_bytes",
                "other_bytes",
            )
        ]

    class Extended(ct.Structure):
        _fields_ = [
            ("basic", Basic),
            ("io", Io),
            ("process_memory", ct.c_size_t),
            ("job_memory", ct.c_size_t),
            ("peak_process", ct.c_size_t),
            ("peak_job", ct.c_size_t),
        ]

    kernel = ct.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.restype = wt.HANDLE
    kernel.CreateJobObjectW.argtypes = [ct.c_void_p, wt.LPCWSTR]
    kernel.SetInformationJobObject.argtypes = [wt.HANDLE, ct.c_int, ct.c_void_p, wt.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
    kernel.GetCurrentProcess.restype = wt.HANDLE
    job = kernel.CreateJobObjectW(None, None)
    limits = Extended()
    # Kill descendants on launcher exit; cap total job CPU time and total committed memory.
    limits.basic.flags = 0x2000 | 0x200 | 0x4
    limits.basic.job_time = cpu * 10_000_000
    limits.job_memory = memory
    if not job or not kernel.SetInformationJobObject(job, 9, ct.byref(limits), ct.sizeof(limits)):
        raise OSError("job limits unavailable")
    if not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        raise OSError("job assignment unavailable")
    return job  # Keep handle alive until process exit, covering the entire tool tree.


def main():
    memory, cpu = int(sys.argv[1]) * 1024 * 1024, int(sys.argv[2])
    try:
        if os.name == "nt":
            job = windows_limits(memory, cpu)
        else:
            import resource

            resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
            resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            job = None
    except (OSError, ValueError):
        return 125
    try:
        result = subprocess.call(sys.argv[3:], stdin=subprocess.DEVNULL)
        return result
    except FileNotFoundError:
        return 127
    finally:
        # Deliberately retain the Windows Job handle; OS closes it on process exit.
        _ = job


if __name__ == "__main__":
    raise SystemExit(main())
