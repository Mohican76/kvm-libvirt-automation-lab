# KVM / libvirt Automation Lab

Hands-on lab work building and automating Linux virtual machines with
KVM/QEMU and libvirt, developed on a memory-constrained Chromebook
(Crostini) rather than a dedicated server.

---

## What's here

| File | What it does |
|---|---|
| `clone.py` | Clones a base qcow2 into a new VM: CoW disk, guestfish network patch, domain XML, `defineXML()` + `create()`, IP discovery |
| `ansible/site.yml` | Idempotent baseline config — `changed=0` on re-run |
| `ansible/vm_lifecycle.yml` | VM lifecycle via `community.libvirt.virt` |
| `ansible/provision_vm.yml` | Full VM provisioning end to end |
| `ansible/inventory.ini.example` | Sanitized inventory template |

---

## Environment

- Host: ChromeOS Crostini (Debian container), ~1 GB usable RAM
- Hypervisor: KVM/QEMU via libvirt (`qemu:///system`)
- Guest: Debian 12 cloud image
- Networking: libvirt `default` NAT (`192.168.122.0/24`)

---

## What broke, and how I fixed it

### 1. Debian 12 cloud image locks the default user

`Login incorrect` on every attempt despite cloud-init credentials.
Cause: `genericcloud` image ships `lock_passwd: true`, and cloud-init
aborts the users module at ~512 MB before applying `chpasswd`.

Fix: bypass cloud-init with `guestfish` writing directly to `/etc/shadow`:

    guestfish --rw -a disk.qcow2
    ><fs> run
    ><fs> mount /dev/sda1 /
    ><fs> command "bash -c 'echo debian:debian | chpasswd'"
    ><fs> umount-all

### 2. cloud-init runcmd never runs if cloud-init aborts

`runcmd` is the last stage. If an earlier module fails, `runcmd` never
executes. A self-repair loop inside cloud-init doesn't work.

Fix: do disk modifications from the host, before boot.

### 3. guestfish write cannot handle escaped newlines

`guestfish: unterminated double quote` on multi-line `write`.
Fix: write to a host temp file, then `upload` into the guest.

### 4. QEMU silently killed mid-provisioning

Script exited with no traceback. Likely OOM at the transition between
the guestfish appliance (~500 MB) and QEMU allocating guest RAM.

Fix: (a) run one VM at a time on this host, (b) `flush=True` plus
numbered step markers so the last printed line pinpoints the failure.

### 5. libvirt domain cannot access files in HOME

`Cannot access storage file ... Permission denied (as uid:64055)`.
Cause: `qemu:///system` runs QEMU as `libvirt-qemu`, which cannot
traverse a home directory at mode 750.

Fix: keep disk images in the libvirt storage pool
(`/var/lib/libvirt/images`).

---

## Running it

Prereqs:

    sudo apt install -y libvirt-daemon-system libvirt-clients virtinst \
                       python3-libvirt cloud-image-utils ansible sshpass

### Clone script

    sudo python3 clone.py

Expected:

    ✓ lab-clone2 at 192.168.122.XXX
      ssh debian@192.168.122.XXX   password: debian

### Ansible

    cd ansible
    cp inventory.ini.example inventory.ini
    # edit inventory.ini with a real host IP and password
    ansible lab -m ping
    ansible-playbook site.yml
    ansible-playbook vm_lifecycle.yml

---

## Known limitations

- Lab-scale, not production (1-3 VMs on a 1 GB host)
- Passwords in inventory rather than SSH keys (planned follow-up)
- provision_vm.yml destroys and rebuilds on every run (check-then-act refactor planned)
- No CI / ansible-lint yet

---

## Skills exercised

KVM, QEMU, libvirt, virsh, guestfish, cloud-init, qcow2/CoW,
VirtIO, systemd-networkd, DHCP/NAT, Python (libvirt bindings),
Ansible (playbooks, idempotency, community.libvirt), Bash.

---

## SSH key authentication

Lab uses ED25519 keys, not passwords.

    ssh-keygen -t ed25519 -f ~/.ssh/lab_key
    ssh-copy-id -i ~/.ssh/lab_key.pub debian@192.168.122.205

Ansible inventory uses ansible_ssh_private_key_file instead of ansible_password. inventory.ini is gitignored.

---

## Idempotency demo (vm_lifecycle.yml)

Same playbook, run twice against lab-clone2:

    Run 1  (lab-clone2 off)     -> changed=1   (Ansible started the VM)
    Run 2  (lab-clone2 running) -> changed=0   (already in desired state, no-op)

This is the check-then-act reconciliation pattern: the playbook describes
desired state, and Ansible makes changes only when necessary. Safe to run
repeatedly in cron, CI, or a deployment pipeline.

---

## Idempotent provisioner (provision_vm.yml)

Refactored from destroy-and-rebuild to check-then-act convergence:

    Run 1  (ansible-vm missing) -> changed=5-6  (provisions the VM)
    Run 2  (ansible-vm running) -> changed=0    (skips 4 tasks, no-ops the rest)

The playbook checks for the domain first, sets a `vm_exists` fact, and
guards all destructive tasks with `when: not vm_exists`. Read-only
probes use `changed_when: false` so they never report spurious changes.

---

## Code quality: ansible-lint

All playbooks pass ansible-lint at the production profile:

    Passed: 0 failure(s), 0 warning(s) on 3 files.
    Last profile that met the validation criteria was production.

Fixes applied to reach this: FQCN prefixes on all builtin modules,
explicit file modes on copy tasks, changed_when/failed_when on
command and shell tasks, pipefail on piped shell commands, and
Jinja templates moved to the end of task names.
