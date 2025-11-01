import subprocess, sys, time, re, os

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

def run_adb(args, serial=None, timeout=None):
    cmd = ["adb"]
    if serial:
        cmd += ["-s", serial]
    cmd += args
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        creationflags=CREATE_NO_WINDOW
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        return out, err, 124
    return out, err, proc.returncode

def adb_path_ok():
    try:
        out, err, rc = run_adb(["version"])
        return rc == 0
    except Exception:
        return False

def adb_devices():
    out, err, rc = run_adb(["devices"])
    if rc != 0: return []
    devs = []
    for line in out.splitlines()[1:]:
        if not line.strip(): continue
        serial, *rest = line.split()
        if len(rest) and rest[0] == "device":
            devs.append(serial)
    return devs

def get_screen_size(serial):
    out, err, rc = run_adb(["shell", "wm", "size"], serial=serial)
    if rc != 0: return None
    m = re.search(r"Physical size:\s*(\d+)x(\d+)", out)
    if not m: return None
    return int(m.group(1)), int(m.group(2))

def get_device_model(serial):
    out, err, rc = run_adb(["shell", "getprop", "ro.product.model"], serial=serial)
    if rc != 0: return None
    return out.strip()

def adb_restart_server():
    run_adb(["kill-server"])
    out, err, rc = run_adb(["start-server"])
    return rc == 0

def run_adb_batch(serial, shell_commands, progress_cb=None, cancel_check=None, sleep_ms=8):
    """
    ส่งคำสั่ง ADB หลายบรรทัดเพื่อวาดรูป
    1) พยายามเปิด interactive shell แล้วเขียนทีละบรรทัดผ่าน stdin (เร็ว)
    2) ถ้าเขียนไม่ได้/โดนปิด -> fallback เป็นรันก้อนละหลายบรรทัดด้วย 'adb shell sh -c "<...>"'
    """
    if not shell_commands:
        return 0, ""
    try:
        proc = subprocess.Popen(
            ["adb", "-s", serial, "shell"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=CREATE_NO_WINDOW
        )
        if proc.stdin is None:
            raise RuntimeError("stdin is None")
        total = len(shell_commands)
        for i, cmd in enumerate(shell_commands, 1):
            if cancel_check and cancel_check():
                break
            try:
                proc.stdin.write(cmd + "\n")
                proc.stdin.flush()
            except Exception as e:

                try:
                    proc.kill()
                except Exception:
                    pass
                raise RuntimeError(f"stdin write error: {e}")
            if progress_cb:
                progress_cb(int(i * 100 / total))
            if sleep_ms > 0:
                time.sleep(sleep_ms / 1000.0)
        try:
            proc.stdin.close()
        except Exception:
            pass
        proc.wait()
        err = ""
        try:
            err = (proc.stderr.read() or "").strip()
        except Exception:
            pass
        return proc.returncode or 0, err
    except Exception:

        pass
    CHUNK = 350
    total = len(shell_commands)
    sent  = 0
    for start in range(0, total, CHUNK):
        if cancel_check and cancel_check():
            break
        chunk = shell_commands[start:start+CHUNK]
        joined = " ; ".join(chunk)
        out, err, rc = run_adb(["shell", "sh", "-c", joined], serial=serial, timeout=180)
        if rc != 0:
            return rc, err or "sh -c batch failed"
        sent = min(start + len(chunk), total)
        if progress_cb:
            progress_cb(int(sent * 100 / total))
    return 0, ""
