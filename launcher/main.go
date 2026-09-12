//go:build windows

package main

import (
    "fmt"
    "os"
    "os/exec"
    "path/filepath"
    "syscall"
    "unsafe"
)

var (
    user32 = syscall.NewLazyDLL("user32.dll")
    messageBoxW = user32.NewProc("MessageBoxW")
)

func utf16Ptr(s string) *uint16 {
    p, _ := syscall.UTF16PtrFromString(s)
    return p
}

func messageBox(title, text string) {
    messageBoxW.Call(0, uintptr(unsafe.Pointer(utf16Ptr(text))), uintptr(unsafe.Pointer(utf16Ptr(title))), 0x10)
}

func exists(name string) bool {
    _, err := exec.LookPath(name)
    return err == nil
}

func main() {
    exe, err := os.Executable()
    if err != nil {
        messageBox("Chartshunter Media Studio", "Uygulama klasörü bulunamadı.")
        return
    }
    root := filepath.Dir(exe)
    bootstrap := filepath.Join(root, "bootstrap.py")
    if _, err := os.Stat(bootstrap); err != nil {
        // GitHub source tree layout support for developer runs.
        alt := filepath.Join(root, "src", "bootstrap.py")
        if _, e := os.Stat(alt); e == nil {
            root = filepath.Join(root, "src")
            bootstrap = alt
        } else {
            messageBox("Chartshunter Media Studio", "bootstrap.py bulunamadı. ZIP içeriğini tamamen çıkardığından emin ol.")
            return
        }
    }

    candidates := [][]string{
        {"pythonw.exe", bootstrap},
        {"python.exe", bootstrap},
        {"pyw.exe", "-3", bootstrap},
        {"py.exe", "-3", bootstrap},
    }
    for _, c := range candidates {
        if !exists(c[0]) {
            continue
        }
        cmd := exec.Command(c[0], c[1:]...)
        cmd.Dir = root
        cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
        if err := cmd.Start(); err == nil {
            return
        }
    }
    messageBox("Chartshunter Media Studio", "Python bulunamadı. Python 3.11+ kurup tekrar deneyin.")
    fmt.Fprintln(os.Stderr, "Python not found")
}
