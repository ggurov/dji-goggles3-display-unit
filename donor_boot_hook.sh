#!/system/bin/sh
# Thin init wrapper — sources the user-owned rc.local on /data (survives slot switches).
RC=/data/local/donor/rc.local
i=0
while [ ! -f "$RC" ] && [ "$i" -lt 30 ]; do
    sleep 1
    i=$((i + 1))
done
if [ ! -f "$RC" ]; then
    exit 0
fi
echo "donor_boot_hook: running $RC" > /dev/kmsg
sh "$RC"
