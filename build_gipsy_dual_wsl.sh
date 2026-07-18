#!/bin/bash
# Build script for GiPSy and GiPSy-mini Rover 4.5.7 firmware.
# Runs in WSL native filesystem for fast I/O.
# GiPSy is temporarily built using GiPSy-mini's hwdef with custom defaults,
# then the original GiPSy hwdef is restored from git.

set -euo pipefail

REPO="/home/guido/ardupilot-build"
PARAM_SOURCE="/mnt/c/Users/Guido's X1/Downloads/gipsy_4ESC_4_5_7_012826.param"
HWDEF_DIR="$REPO/libraries/AP_HAL_ChibiOS/hwdef"
BACKUP_DIR="/tmp/GiPSy-original-backup-$(date +%s)"
LOGFILE="$REPO/build_gipsy_dual.log"
WAF="python3 modules/waf/waf-light"
DATE=$(date +%Y-%m-%d)
FIRMWARE_DIR="/mnt/g/GIT/ardupilot/firmware"

# Ensure we restore original GiPSy hwdef and bootloader on exit or error
restore_gipsy() {
    local rc=$?
    if [ -d "$BACKUP_DIR" ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Restoring original GiPSy hwdef from backup..." | tee -a "$LOGFILE"
        rm -rf "$HWDEF_DIR/GiPSy"
        mv "$BACKUP_DIR" "$HWDEF_DIR/GiPSy"
    fi
    if [ -f "/tmp/GiPSy_bl.bin.orig" ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Restoring original GiPSy bootloader..." | tee -a "$LOGFILE"
        cp "/tmp/GiPSy_bl.bin.orig" "$REPO/Tools/bootloaders/GiPSy_bl.bin"
        rm -f "/tmp/GiPSy_bl.bin.orig"
    fi
    # Also ensure git index version is restored (in case backup was corrupted)
    cd "$REPO"
    git checkout -- libraries/AP_HAL_ChibiOS/hwdef/GiPSy/ 2>/dev/null || true
    return $rc
}
trap restore_gipsy EXIT

cd "$REPO"

# Stop any stale background monitors/notifications from earlier runs
exec > >(tee -a "$LOGFILE")
exec 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting dual GiPSy/GiPSy-mini build..."

# Validate parameter source
if [ ! -f "$PARAM_SOURCE" ]; then
    echo "ERROR: Parameter file not found: $PARAM_SOURCE"
    exit 1
fi

# Clean stale build directories so waf does not pick up a wrong configure cache
rm -rf "$REPO/build/GiPSy" "$REPO/build/GiPSy-mini" "$REPO/build/GiPSy_mini_4in1" "$REPO/build/GiPSy_mini"
rm -f "$REPO/.lock-waf_linux_build"

# Ensure GiPSy is at git HEAD before we start
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Resetting GiPSy hwdef to git HEAD..."
git checkout -- libraries/AP_HAL_ChibiOS/hwdef/GiPSy/

# Backup original GiPSy hwdef and bootloader
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backing up original GiPSy hwdef and bootloader..."
cp -a "$HWDEF_DIR/GiPSy" "$BACKUP_DIR"
cp "$REPO/Tools/bootloaders/GiPSy_bl.bin" "/tmp/GiPSy_bl.bin.orig"

# Replace GiPSy hwdef with GiPSy-mini's (same hardware) and install custom defaults
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Swapping GiPSy hwdef with GiPSy-mini's..."
cp "$HWDEF_DIR/GiPSy-mini/hwdef.dat" "$HWDEF_DIR/GiPSy/hwdef.dat"
cp "$HWDEF_DIR/GiPSy-mini/hwdef-bl.dat" "$HWDEF_DIR/GiPSy/hwdef-bl.dat"
cp "$PARAM_SOURCE" "$HWDEF_DIR/GiPSy/defaults.parm"

# --- GiPSy (new parameters) ---
# 1) Build bootloader first so the correct board-ID 2002 bootloader is available
#    for embedding into the Rover firmware.
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Configuring GiPSy bootloader..."
$WAF configure --board=GiPSy --bootloader
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Building GiPSy bootloader..."
$WAF bootloader

# Make the newly built bootloader the one embedded in the Rover with-bl hex.
cp "$REPO/build/GiPSy/bin/AP_Bootloader.bin" "$REPO/Tools/bootloaders/GiPSy_bl.bin"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Configuring GiPSy Rover..."
$WAF configure --board=GiPSy
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Building GiPSy Rover..."
$WAF rover

# Restore original GiPSy hwdef and bootloader before building GiPSy-mini
restore_gipsy
# Remove the trap's restore marker so it does not run again on the next exit
rm -rf "$BACKUP_DIR"
rm -f "/tmp/GiPSy_bl.bin.orig"

# --- GiPSy-mini (repo defaults) ---
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Configuring GiPSy-mini bootloader..."
$WAF configure --board=GiPSy-mini --bootloader
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Building GiPSy-mini bootloader..."
$WAF bootloader

# Refresh the repo bootloader so the with-bl hex uses the freshly built one
cp "$REPO/build/GiPSy-mini/bin/AP_Bootloader.bin" "$REPO/Tools/bootloaders/GiPSy-mini_bl.bin"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Configuring GiPSy-mini Rover..."
$WAF configure --board=GiPSy-mini
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Building GiPSy-mini Rover..."
$WAF rover

# Rename output folders to requested names
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Renaming output folders..."
mv "$REPO/build/GiPSy" "$REPO/build/GiPSy_mini_4in1"
mv "$REPO/build/GiPSy-mini" "$REPO/build/GiPSy_mini"

# Copy final binaries to firmware/<target>_<date>/ folders
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Copying firmware packages to $FIRMWARE_DIR..."
for target in GiPSy_mini_4in1 GiPSy_mini; do
    dest_dir="$FIRMWARE_DIR/${target}_${DATE}"
    mkdir -p "$dest_dir"
    cp "$REPO/build/$target/bin/ardurover.bin" "$dest_dir/${target}_${DATE}.bin"
    cp "$REPO/build/$target/bin/ardurover.apj" "$dest_dir/${target}_${DATE}.apj"
    cp "$REPO/build/$target/bin/ardurover_with_bl.hex" "$dest_dir/${target}_${DATE}_with_bl.hex"
    cp "$REPO/build/$target/bin/AP_Bootloader.bin" "$dest_dir/${target}_${DATE}_bl.bin"
    cp "$REPO/build/$target/bin/AP_Bootloader.hex" "$dest_dir/${target}_${DATE}_bl.hex"
    cp "$REPO/build/$target/bin/AP_Bootloader.apj" "$dest_dir/${target}_${DATE}_bl.apj"
done

# Verify outputs
echo ""
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Build complete. Output files:"
echo "--- GiPSy_mini_4in1 (new parameters) ---"
ls -la "$REPO/build/GiPSy_mini_4in1/bin/"* || true
echo "--- GiPSy_mini (repo defaults) ---"
ls -la "$REPO/build/GiPSy_mini/bin/"* || true

# Report board IDs in the generated .apj files
echo ""
echo "Board IDs in generated firmware:"
python3 - <<'PY'
import json, os, sys
repo = "/home/guido/ardupilot-build"
for d in ["GiPSy_mini_4in1", "GiPSy_mini"]:
    apj = os.path.join(repo, "build", d, "bin", "ardurover.apj")
    if os.path.exists(apj):
        data = json.load(open(apj))
        print(f"{d}: board_id={data.get('board_id')}")
PY

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Done."
