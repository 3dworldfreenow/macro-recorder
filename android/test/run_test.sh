#!/bin/bash
# Runs on the GitHub Android emulator. Installs the APK, turns on the
# permissions with adb, runs a test sequence and checks the log.
set -x
PKG=com.keypresser.touch
OUT=android-shots
mkdir -p $OUT
adb install -r -g KeyPresser.apk || exit 1
adb shell settings put secure enabled_accessibility_services $PKG/$PKG.KPService
adb shell settings put secure accessibility_enabled 1
adb shell appops set $PKG SYSTEM_ALERT_WINDOW allow
sleep 3
adb shell dumpsys accessibility | grep -i keypresser | head -5

# main screen with the test sequence loaded
IMP=$(base64 -w0 android/test/seq_settings.json)
adb shell am start -n $PKG/.MainActivity --es kp_import_b64 "$IMP"
sleep 6
adb exec-out screencap -p > $OUT/1_main.png

# the step editor
adb shell am start -n $PKG/.MainActivity --ez kp_open_editor true --ei kp_editor_index 1
sleep 4
adb exec-out screencap -p > $OUT/2_step_editor.png
adb shell input keyevent KEYCODE_BACK
sleep 2

# run the test sequence
adb shell am start -n $PKG/.MainActivity --es kp_run_b64 "$IMP" --ez kp_log true --ei kp_delay 1
sleep 5
adb exec-out screencap -p > $OUT/3_running.png
adb shell dumpsys window windows | awk '/Window #/{p=0} /Window #.*u0 com.keypresser.touch}/{p=1} p' | head -60
adb shell run-as $PKG cat files/run_log.txt | head -3
sleep 4
adb exec-out screencap -p > $OUT/4_running_apps.png
for i in $(seq 1 60); do
  if adb shell run-as $PKG cat files/run_log.txt 2>/dev/null | grep -qE " (done|stopped)"; then break; fi
  sleep 2
done
adb shell run-as $PKG cat files/run_log.txt | tee run_log.txt
adb exec-out screencap -p > $OUT/5_after.png

# floating panel during a wait (over Settings and on the home screen)
cat > /tmp/seq_wait.json <<'J'
{"loops": 1, "steps": [
 {"type": "app", "pkg": "com.android.settings", "app_label": "Settings", "amin": 6, "amax": 6},
 {"type": "nav", "nav": "Home", "amin": 6, "amax": 6}
]}
J
W=$(base64 -w0 /tmp/seq_wait.json)
adb shell am start -n $PKG/.MainActivity --es kp_run_b64 "$W" --ez kp_log true --ei kp_delay 1
sleep 5
adb exec-out screencap -p > $OUT/6_panel_over_settings.png
sleep 6
adb exec-out screencap -p > $OUT/7_panel_home.png
sleep 4

set +x
fail=0
check() { if grep -qE "$1" run_log.txt; then echo "OK   $2"; else echo "FAIL $2"; fail=1; fi; }
check "1 app ok com.android.settings" "opened Settings app"
check "2 find found .*Apps" "found and tapped 'Apps'"
check "3 read match" "Apps page opened (read check)"
check "4 nav Back" "pressed Back"
check "5 read match" "back on main Settings (read check)"
check "6 link (ok|fail)" "link step ran"
check "7 nav Home" "pressed Home"
check " done" "sequence finished"
if grep -q "stopped" run_log.txt; then echo "FAIL sequence stopped early"; fail=1; fi
if [ $fail -eq 0 ]; then echo "ANDROID TEST PASSED"; else echo "ANDROID TEST FAILED"; fi
exit $fail
