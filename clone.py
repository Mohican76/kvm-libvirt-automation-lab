#!/usr/bin/env python3
"""Clone debian-lab's base disk into lab-clone2 with full logging."""
import libvirt
import os
import subprocess
import tempfile
import time

URI = "qemu:///system"
NEW_NAME = "lab-clone2"
NEW_DISK = "/var/lib/libvirt/images/lab-clone2.qcow2"
BASE = "/var/lib/libvirt/images/debian-12-genericcloud-amd64.qcow2"

print("[1] Connecting to libvirt...", flush=True)
conn = libvirt.open(URI)
print(f"    connected: {conn.getURI()}", flush=True)

# --- Cleanup prior run ---
print("[2] Cleanup prior run...", flush=True)
try:
    old = conn.lookupByName(NEW_NAME)
    if old.isActive():
        old.destroy()
    old.undefine()
    print(f"    removed old {NEW_NAME}", flush=True)
except libvirt.libvirtError:
    print("    nothing to clean up", flush=True)

# --- Create CoW disk ---
print("[3] Creating CoW disk...", flush=True)
subprocess.run(["sudo", "rm", "-f", NEW_DISK], check=False)
subprocess.run([
    "sudo", "qemu-img", "create", "-f", "qcow2", "-F", "qcow2",
    "-b", BASE, NEW_DISK, "20G"
], check=True)
print(f"    created: {NEW_DISK}", flush=True)

# --- Patch network config via guestfish ---
print("[4] Patching network config via guestfish...", flush=True)
dhcp_conf = "[Match]\nName=en*\n[Network]\nDHCP=yes\n"
with tempfile.NamedTemporaryFile("w", suffix=".network", delete=False) as tf:
    tf.write(dhcp_conf)
    tmp_path = tf.name

gf = f"""run
mount /dev/sda1 /
upload {tmp_path} /etc/systemd/network/20-dhcp.network
umount-all
"""
try:
    subprocess.run(
        ["sudo", "guestfish", "--rw", "-a", NEW_DISK],
        input=gf.encode(), check=True,
    )
finally:
    os.unlink(tmp_path)
print("    network config patched", flush=True)

# --- Build domain XML ---
print("[5] Building domain XML...", flush=True)
xml = f"""
<domain type='kvm'>
  <name>{NEW_NAME}</name>
  <memory unit='MiB'>512</memory>
  <vcpu>2</vcpu>
  <os><type arch='x86_64'>hvm</type><boot dev='hd'/></os>
  <features><acpi/><apic/></features>
  <cpu mode='host-passthrough'/>
  <devices>
    <disk type='file' device='disk'>
      <driver name='qemu' type='qcow2'/>
      <source file='{NEW_DISK}'/>
      <target dev='vda' bus='virtio'/>
    </disk>
    <interface type='network'>
      <source network='default'/>
      <model type='virtio'/>
    </interface>
    <serial type='pty'/>
    <console type='pty'/>
  </devices>
</domain>
"""

print("[6] About to defineXML...", flush=True)
try:
    dom = conn.defineXML(xml)
    print(f"    defineXML OK  uuid={dom.UUIDString()}", flush=True)
except Exception as e:
    print(f"    defineXML FAILED: {type(e).__name__}: {e}", flush=True)
    raise

print("[7] About to create()...", flush=True)
try:
    dom.create()
    print(f"    Started {NEW_NAME}  state={dom.state()}", flush=True)
except Exception as e:
    print(f"    create() FAILED: {type(e).__name__}: {e}", flush=True)
    raise

# --- Wait for IP ---
print("[8] Waiting for IP...", flush=True)
for i in range(60):
    time.sleep(3)
    try:
        addrs = dom.interfaceAddresses(libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE)
        for iface in addrs.values():
            for a in iface.get("addrs", []):
                if a.get("type") == libvirt.VIR_IP_ADDR_TYPE_IPV4:
                    print(f"✓ {NEW_NAME} at {a['addr']}", flush=True)
                    print(f"  ssh debian@{a['addr']}   password: debian", flush=True)
                    raise SystemExit(0)
    except libvirt.libvirtError:
        pass
    if i % 10 == 9:
        print(f"    still waiting... ({(i+1)*3}s)", flush=True)

print(f"⚠ No IP. Debug: virsh console {NEW_NAME}", flush=True)
