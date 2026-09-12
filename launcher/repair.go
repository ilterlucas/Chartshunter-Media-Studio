//go:build windows

package main

import (
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

func ptr(s string) *uint16 { p, _ := syscall.UTF16PtrFromString(s); return p }
func box(title, text string) { messageBoxW.Call(0, uintptr(unsafe.Pointer(ptr(text))), uintptr(unsafe.Pointer(ptr(title))), 0x10) }
func has(name string) bool { _, err := exec.LookPath(name); return err == nil }

func main() {
    exe, err := os.Executable()
    if err != nil { box("Chartshunter Repair & Update", "Uygulama klasörü bulunamadı."); return }
    root := filepath.Dir(exe)
    bootstrap := filepath.Join(root, "bootstrap.py")
    if _, err := os.Stat(bootstrap); err != nil {
        alt := filepath.Join(root, "src", "bootstrap.py")
        if _, e := os.Stat(alt); e == nil { root = filepath.Join(root, "src"); bootstrap = alt } else { box("Chartshunter Repair & Update", "bootstrap.py bulunamadı."); return }
    }
    candidates := [][]string{{"pythonw.exe", bootstrap, "--repair"}, {"python.exe", bootstrap, "--repair"}, {"pyw.exe", "-3", bootstrap, "--repair"}, {"py.exe", "-3", bootstrap, "--repair"}}
    for _, c := range candidates {
        if !has(c[0]) { continue }
        cmd := exec.Command(c[0], c[1:]...)
        cmd.Dir = root
        cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
        if err := cmd.Start(); err == nil { return }
    }
    box("Chartshunter Repair & Update", "Python bulunamadı. Python 3.11+ kurup tekrar deneyin.")
}
