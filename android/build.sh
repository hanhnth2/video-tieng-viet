#!/usr/bin/env bash
# Đóng gói ứng dụng Android "Video Tiếng Việt" thành APK.
# Cần: JDK 8+, aapt2, dx (dalvik-exchange), zipalign, apksigner, android.jar (API 23+)
#   Ubuntu: sudo apt install default-jdk android-sdk-platform-23 android-sdk-build-tools dalvik-exchange apksigner zipalign
set -euo pipefail
cd "$(dirname "$0")"
ANDROID_JAR=${ANDROID_JAR:-/usr/lib/android-sdk/platforms/android-23/android.jar}
DX=${DX:-dalvik-exchange}
OUT=build
rm -rf "$OUT"; mkdir -p "$OUT"/{res,gen,classes}

echo "[1/6] Biên dịch tài nguyên"
aapt2 compile --dir res -o "$OUT/res/res.zip"

echo "[2/6] Liên kết manifest + tài nguyên"
aapt2 link -o "$OUT/base.apk" -I "$ANDROID_JAR" --manifest AndroidManifest.xml \
  --min-sdk-version 24 --target-sdk-version 34 --version-code 4 --version-name 1.3 \
  -A assets --java "$OUT/gen" --auto-add-overlay "$OUT/res/res.zip"

echo "[3/6] Biên dịch Java"
javac --release 8 -encoding UTF-8 -nowarn -classpath "$ANDROID_JAR" -d "$OUT/classes" \
  $(find src "$OUT/gen" -name '*.java') 2>&1 | grep -v "^warning\|^Note\|bootstrap" || true
test -f "$OUT/classes/com/ngothihonghanh/videoviet/MainActivity.class"

echo "[4/6] Chuyển sang mã Dalvik (classes.dex)"
$DX --dex --min-sdk-version=24 --output="$OUT/classes.dex" "$OUT/classes"

echo "[5/6] Đóng gói + căn chỉnh"
cp "$OUT/base.apk" "$OUT/unsigned.apk"
(cd "$OUT" && zip -q -j unsigned.apk classes.dex)
zipalign -f -p 4 "$OUT/unsigned.apk" "$OUT/aligned.apk"

echo "[6/6] Ký ứng dụng"
if [ ! -f videoviet.keystore ]; then
  keytool -genkeypair -keystore videoviet.keystore -storepass videoviet -keypass videoviet -alias videoviet \
    -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=Ngo Thi Hong Hanh, O=Video Tieng Viet, C=VN" >/dev/null 2>&1
fi
apksigner sign --ks videoviet.keystore --ks-pass pass:videoviet --key-pass pass:videoviet --ks-key-alias videoviet \
  --min-sdk-version 24 --out "$OUT/VideoTiengViet.apk" "$OUT/aligned.apk"
apksigner verify --print-certs "$OUT/VideoTiengViet.apk" | head -2
ls -la "$OUT/VideoTiengViet.apk"
