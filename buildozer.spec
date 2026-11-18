[app]
title = Khalil Video Downloader
package.name = khaliddownloader
package.domain = com.khalil
source.dir = .
source.include_exts = py,kv
version = 1.0.0
requirements = python3,kivy==2.3.0,yt-dlp,certifi,openssl,pyjnius,android
orientation = portrait
fullscreen = 0
android.permissions = INTERNET,ACCESS_NETWORK_STATE,WRITE_EXTERNAL_STORAGE
android.api = 33
android.minapi = 21
android.ndk = 25b
android.archs = arm64-v8a
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 1
