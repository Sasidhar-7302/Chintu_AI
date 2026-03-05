#include "flutter_window.h"

#include <optional>
#include <windows.h>

#include "flutter/generated_plugin_registrant.h"

FlutterWindow::FlutterWindow(const flutter::DartProject& project)
    : project_(project) {}

FlutterWindow::~FlutterWindow() {}

bool FlutterWindow::OnCreate() {
  if (!Win32Window::OnCreate()) {
    return false;
  }

  RECT frame = GetClientArea();

  // The size here must match the window dimensions to avoid unnecessary surface
  // creation / destruction in the startup path.
  flutter_controller_ = std::make_unique<flutter::FlutterViewController>(
      frame.right - frame.left, frame.bottom - frame.top, project_);
  // Ensure that basic setup of the controller was successful.
  if (!flutter_controller_->engine() || !flutter_controller_->view()) {
    return false;
  }
  RegisterPlugins(flutter_controller_->engine());
  SetChildContent(flutter_controller_->view()->GetNativeWindow());

  // Exclude the UI window from screen-capture by default.
  // This is the same API many "privacy overlay" apps use to hide their window in screen shares.
  // Note: some full-desktop capture modes may still show the window depending on the capture stack.
#ifndef WDA_EXCLUDEFROMCAPTURE
#define WDA_EXCLUDEFROMCAPTURE 0x00000011
#endif
  HWND hwnd = GetHandle();
  if (hwnd) {
    ::SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE);
  }

  // Platform channel so the Flutter UI can toggle stealth mode on/off.
  static constexpr char kStealthChannelName[] = "chintu/stealth_window";
  stealth_channel_ = std::make_unique<flutter::MethodChannel<flutter::EncodableValue>>(
      flutter_controller_->engine()->messenger(),
      kStealthChannelName,
      &flutter::StandardMethodCodec::GetInstance());

  stealth_channel_->SetMethodCallHandler([hwnd](const auto& call, auto result) {
    if (!hwnd) {
      result->Error("no_window", "No top-level window handle available.");
      return;
    }

    const std::string& method = call.method_name();
    if (method == "setStealthMode") {
      bool enabled = true;
      if (call.arguments() && std::holds_alternative<bool>(*call.arguments())) {
        enabled = std::get<bool>(*call.arguments());
      }

      const DWORD affinity = enabled ? WDA_EXCLUDEFROMCAPTURE : 0;
      const BOOL ok = ::SetWindowDisplayAffinity(hwnd, affinity);
      if (!ok) {
        result->Error("set_failed", "SetWindowDisplayAffinity failed.");
        return;
      }
      result->Success(flutter::EncodableValue(true));
      return;
    }

    if (method == "isSupported") {
      result->Success(flutter::EncodableValue(true));
      return;
    }

    result->NotImplemented();
  });

  flutter_controller_->engine()->SetNextFrameCallback([&]() {
    this->Show();
  });

  // Flutter can complete the first frame before the "show window" callback is
  // registered. The following call ensures a frame is pending to ensure the
  // window is shown. It is a no-op if the first frame hasn't completed yet.
  flutter_controller_->ForceRedraw();

  return true;
}

void FlutterWindow::OnDestroy() {
  if (flutter_controller_) {
    flutter_controller_ = nullptr;
  }

  Win32Window::OnDestroy();
}

LRESULT
FlutterWindow::MessageHandler(HWND hwnd, UINT const message,
                              WPARAM const wparam,
                              LPARAM const lparam) noexcept {
  // Give Flutter, including plugins, an opportunity to handle window messages.
  if (flutter_controller_) {
    std::optional<LRESULT> result =
        flutter_controller_->HandleTopLevelWindowProc(hwnd, message, wparam,
                                                      lparam);
    if (result) {
      return *result;
    }
  }

  switch (message) {
    case WM_FONTCHANGE:
      flutter_controller_->engine()->ReloadSystemFonts();
      break;
  }

  return Win32Window::MessageHandler(hwnd, message, wparam, lparam);
}
