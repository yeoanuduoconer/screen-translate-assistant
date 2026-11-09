#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out="$root/build"
work="$(mktemp -d "${TMPDIR:-/tmp}/screen-translate-ios.XXXXXXXX")"
trap 'rm -rf -- "$work"' EXIT

mkdir -p "$out" "$work/Payload"
xcodebuild -project "$root/ScreenTranslate.xcodeproj" \
  -target ScreenTranslate -configuration Release -sdk iphoneos \
  CONFIGURATION_BUILD_DIR="$work/products" OBJROOT="$work/objects" SYMROOT="$work/symbols" \
  CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO build

test -x "$work/products/ScreenTranslate.app/ScreenTranslate"
test -f "$work/products/ScreenTranslate.app/Bridge.js"
test -f "$work/products/ScreenTranslate.app/Demo.html"
ditto "$work/products/ScreenTranslate.app" "$work/Payload/ScreenTranslate.app"
ditto -c -k --keepParent "$work/Payload" "$work/ScreenTranslate-unsigned.ipa"
mv -f -- "$work/ScreenTranslate-unsigned.ipa" "$out/ScreenTranslate-unsigned.ipa"
printf '%s\n' "$out/ScreenTranslate-unsigned.ipa"
