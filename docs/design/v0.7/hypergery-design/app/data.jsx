/* HyperGery mock data — SMX/ASIX classroom scenario. Exposes window.HG */
(function () {
  const HOST_LOCAL = "aula12-pc03";

  const vms = [
    { id: "vm-dc01", name: "WS2022-DC01", lab: "asix-ad-lab", host: HOST_LOCAL, os: "Windows Server 2022", role: "AD",
      state: "running", cpu: 2, cpuLoad: 14, ram: 4096, ramUsed: 2870, disk: 60, diskUsed: 23.4, display: "VNC",
      ip: "10.20.0.10", mac: "52:54:00:a1:0c:01", uuid: "5f3b2a10-9c44-4e21-b8f1-0a1b2c3d4e10", uptime: "2d 04h", vnc: ":1", spicePort: null },
    { id: "vm-dns01", name: "Ubuntu-DNS01", lab: "asix-ad-lab", host: HOST_LOCAL, os: "Ubuntu Server 24.04", role: "DNS",
      state: "running", cpu: 1, cpuLoad: 6, ram: 2048, ramUsed: 740, disk: 25, diskUsed: 6.1, display: "VNC",
      ip: "10.20.0.11", mac: "52:54:00:a1:0c:02", uuid: "1a2b3c4d-5e6f-4012-8a9b-0c1d2e3f4a02", uptime: "2d 04h", vnc: ":2", spicePort: null },
    { id: "vm-win11", name: "Win11-Client01", lab: "asix-ad-lab", host: HOST_LOCAL, os: "Windows 11 Pro", role: "Client",
      state: "running", cpu: 2, cpuLoad: 31, ram: 4096, ramUsed: 3310, disk: 64, diskUsed: 41.2, display: "SPICE",
      ip: "10.20.0.50", mac: "52:54:00:a1:0c:03", uuid: "9d8c7b6a-1234-4f56-9abc-0d1e2f3a4b03", uptime: "06h 11m", vnc: null, spicePort: 5901 },
    { id: "vm-win11b", name: "Win11-Client02", lab: "asix-ad-lab", host: HOST_LOCAL, os: "Windows 11 Pro", role: "Client",
      state: "shutoff", cpu: 2, cpuLoad: 0, ram: 4096, ramUsed: 0, disk: 64, diskUsed: 39.8, display: "VNC",
      ip: null, mac: "52:54:00:a1:0c:04", uuid: "0e1f2a3b-4c5d-4e6f-8a9b-0c1d2e3f4b04", uptime: "—", vnc: ":3", spicePort: null },
    { id: "vm-router", name: "VyOS-Router", lab: "smx-redes-lab", host: HOST_LOCAL, os: "VyOS 1.4", role: "Router",
      state: "running", cpu: 1, cpuLoad: 9, ram: 1024, ramUsed: 380, disk: 8, diskUsed: 2.4, display: "VNC",
      ip: "10.30.0.1", mac: "52:54:00:b2:0d:01", uuid: "7766aa55-bb44-4cc3-9dd2-0e1f2a3b4c05", uptime: "5d 09h", vnc: ":4", spicePort: null },
    { id: "vm-web01", name: "Debian-WEB01", lab: "smx-redes-lab", host: HOST_LOCAL, os: "Debian 12", role: "WEB",
      state: "running", cpu: 1, cpuLoad: 11, ram: 2048, ramUsed: 910, disk: 20, diskUsed: 7.7, display: "VNC",
      ip: "10.30.0.20", mac: "52:54:00:b2:0d:02", uuid: "abcd1234-5678-49ab-bcde-0f1a2b3c4d06", uptime: "5d 09h", vnc: ":5", spicePort: null },
    { id: "vm-db01", name: "Debian-DB01", lab: "smx-redes-lab", host: HOST_LOCAL, os: "Debian 12 + MariaDB", role: "DB",
      state: "paused", cpu: 2, cpuLoad: 0, ram: 3072, ramUsed: 1180, disk: 40, diskUsed: 14.9, display: "VNC",
      ip: "10.30.0.21", mac: "52:54:00:b2:0d:03", uuid: "fed09876-5432-41fe-dcba-0a1b2c3d4e07", uptime: "paused", vnc: ":6", spicePort: null },
    { id: "vm-cl-linux", name: "Ubuntu-Desktop01", lab: "smx-redes-lab", host: HOST_LOCAL, os: "Ubuntu 24.04 Desktop", role: "Client",
      state: "shutoff", cpu: 2, cpuLoad: 0, ram: 4096, ramUsed: 0, disk: 40, diskUsed: 18.2, display: "VNC",
      ip: null, mac: "52:54:00:b2:0d:04", uuid: "13572468-9ace-4bdf-8024-0b1c2d3e4f08", uptime: "—", vnc: ":7", spicePort: null },
    { id: "vm-ad-bak", name: "WS2022-DC02", lab: "asix-ad-lab", host: "aula12-pc07", os: "Windows Server 2022", role: "AD",
      state: "running", cpu: 2, cpuLoad: 8, ram: 4096, ramUsed: 2410, disk: 60, diskUsed: 22.1, display: "VNC",
      ip: "10.20.0.12", mac: "52:54:00:a1:0c:09", uuid: "24681357-ace9-4fdb-9753-0c1d2e3f4a09", uptime: "1d 02h", vnc: ":1", spicePort: null },
    { id: "vm-unknown", name: "lab-import-tmp", lab: null, host: HOST_LOCAL, os: "Unknown", role: null,
      state: "unknown", cpu: 1, cpuLoad: 0, ram: 1024, ramUsed: 0, disk: 10, diskUsed: 0.0, display: "VNC",
      ip: null, mac: "52:54:00:ff:ff:ff", uuid: "00000000-0000-0000-0000-000000000000", uptime: "—", vnc: null, spicePort: null },
  ];

  const labs = [
    { id: "asix-ad-lab", name: "ASIX · Active Directory", subnet: "10.20.0.0/24", bridge: "hgbr-3f9a", net: "hg-net-asix-ad-lab",
      templates: ["ws2022-base", "ubuntu-server-base", "win11-client"], desc: "Dominio Windows Server 2022, DNS y clientes unidos al dominio.",
      vms: ["vm-dc01", "vm-dns01", "vm-win11", "vm-win11b", "vm-ad-bak"] },
    { id: "smx-redes-lab", name: "SMX · Redes y Servicios", subnet: "10.30.0.0/24", bridge: "hgbr-7c12", net: "hg-net-smx-redes-lab",
      templates: ["vyos-router", "debian-base", "ubuntu-desktop"], desc: "Router VyOS, servidor web, base de datos y clientes Linux.",
      vms: ["vm-router", "vm-web01", "vm-db01", "vm-cl-linux"] },
  ];

  const vmTemplates = [
    { id: "ws2022-base", name: "Windows Server 2022 Base", os: "Windows", ram: 4096, vcpu: 2, disk: 60, display: "VNC" },
    { id: "win11-client", name: "Windows 11 Client", os: "Windows", ram: 4096, vcpu: 2, disk: 64, display: "SPICE" },
    { id: "ubuntu-server-base", name: "Ubuntu Server 24.04", os: "Linux", ram: 2048, vcpu: 1, disk: 25, display: "VNC" },
    { id: "debian-base", name: "Debian 12 Base", os: "Linux", ram: 2048, vcpu: 1, disk: 20, display: "VNC" },
    { id: "vyos-router", name: "VyOS 1.4 Router", os: "Linux", ram: 1024, vcpu: 1, disk: 8, display: "VNC" },
    { id: "ubuntu-desktop", name: "Ubuntu 24.04 Desktop", os: "Linux", ram: 4096, vcpu: 2, disk: 40, display: "VNC" },
  ];

  const labTemplates = [
    { id: "asix-ad-lab", name: "ASIX AD Domain Lab", planned: 5, ram: 18432, vms: "DC01 · DNS01 · DC02 · 2× Win11" },
    { id: "smx-redes-lab", name: "SMX Networking Lab", planned: 4, ram: 11264, vms: "Router · WEB · DB · Client" },
    { id: "lamp-stack", name: "LAMP Stack Practice", planned: 3, ram: 6144, vms: "WEB · DB · Client" },
  ];

  const hub = {
    url: "http://192.168.1.150:8765", online: true, health: "healthy", latency: 23,
    hostsOnline: 2, hostsTotal: 3, vmRecords: 10, nasWritable: true, lastCheck: "hace 18 s",
    nasRoot: "/share/CACHEDEV2_DATA/Gerard/hypergery", docker: "healthy",
  };

  const hosts = [
    { id: "aula12-pc03", name: "aula12-pc03 (este equipo)", local: true, status: "online", kvm: true, libvirt: true,
      ramFree: 9.2, ramTotal: 32, diskFree: 410, diskTotal: 960, activeVms: 7, heartbeat: "hace 4 s", ip: "192.168.1.103", cpu: "i7-12700" },
    { id: "aula12-pc07", name: "aula12-pc07", local: false, status: "online", kvm: true, libvirt: true,
      ramFree: 21.4, ramTotal: 32, diskFree: 612, diskTotal: 960, activeVms: 1, heartbeat: "hace 11 s", ip: "192.168.1.107", cpu: "i7-12700" },
    { id: "aula12-pc09", name: "aula12-pc09", local: false, status: "offline", kvm: false, libvirt: false,
      ramFree: 0, ramTotal: 16, diskFree: 0, diskTotal: 480, activeVms: 0, heartbeat: "hace 6 min", ip: "192.168.1.109", cpu: "i5-10400" },
  ];

  const migrations = [
    { id: "mig-20260604-7f3a", vm: "Debian-WEB01", target: "Win... no", from: "aula12-pc03", to: "aula12-pc07",
      targetVm: "Debian-WEB01-copy", state: "done", when: "ayer 17:42", size: "7.7 GB", duration: "3m 12s" },
    { id: "mig-20260602-1b9c", vm: "Ubuntu-Desktop01", target: "", from: "aula12-pc03", to: "aula12-pc07",
      targetVm: "Ubuntu-Desktop01-clone", state: "done", when: "02 jun 11:08", size: "18.2 GB", duration: "6m 47s" },
    { id: "mig-20260531-4d2e", vm: "WS2022-DC02", target: "", from: "aula12-pc07", to: "aula12-pc09",
      targetVm: "WS2022-DC02-bak", state: "failed", when: "31 may 09:20", size: "—", duration: "—", error: "target host offline durante preflight" },
  ];

  const diagnostics = [
    { status: "OK", name: "python", detail: "3.12.3", critical: false },
    { status: "OK", name: "hub url", detail: "http://192.168.1.150:8765", src: "environment", critical: false },
    { status: "OK", name: "host id", detail: "aula12-pc03", src: "config", critical: false },
    { status: "OK", name: "/dev/kvm", detail: "exists and accessible", critical: true },
    { status: "OK", name: "user groups", detail: "kvm/libvirt present", critical: false },
    { status: "OK", name: "qemu-img", detail: "/usr/bin/qemu-img", critical: true },
    { status: "OK", name: "virsh", detail: "/usr/bin/virsh", critical: true },
    { status: "OK", name: "virt-viewer", detail: "/usr/bin/virt-viewer", critical: false },
    { status: "OK", name: "libvirt", detail: "connected to qemu:///system", critical: true },
    { status: "OK", name: "nas staging path", detail: "/mnt/hypergery-nas/hypergery  writable=true", src: "environment", critical: true },
    { status: "OK", name: "docker folder", detail: "/opt/hypergery/docker", critical: false },
    { status: "WARN", name: "docker compose", detail: "no disponible en este equipo (Hub corre en NAS)", critical: false },
    { status: "OK", name: "hub reachable", detail: "{'status': 'healthy', 'hosts': 2}", critical: true },
    { status: "OK", name: "hub vm inventory", detail: "10 VM record(s)", critical: false },
  ];

  const now = new Date();
  function ts(minAgo) {
    const d = new Date(now.getTime() - minAgo * 60000);
    return d.toTimeString().slice(0, 8);
  }
  const logs = [
    { t: ts(0.1), src: "vm", level: "info", msg: "Win11-Client01: SPICE display ready on port 5901" },
    { t: ts(0.4), src: "console", level: "info", msg: "Console window opened for WS2022-DC01 (VNC :1) — input captured" },
    { t: ts(1), src: "hub", level: "info", msg: "Heartbeat received from aula12-pc07 (online, 1 active VM)" },
    { t: ts(2), src: "vm", level: "info", msg: "Debian-DB01: domain paused by user" },
    { t: ts(4), src: "migration", level: "info", msg: "mig-20260604-7f3a: state=done · source VM intact · UUID/MAC regenerated on target" },
    { t: ts(7), src: "agent", level: "info", msg: "aula12-pc07 agent: import_vm_package completed in 3m12s" },
    { t: ts(9), src: "vm", level: "info", msg: "VyOS-Router: ACPI shutdown requested → running (cancelled)" },
    { t: ts(14), src: "hub", level: "warn", msg: "aula12-pc09 missed heartbeat (last seen 6 min ago) → marked offline" },
    { t: ts(15), src: "migration", level: "error", msg: "mig-20260531-4d2e: failed — target host offline during preflight" },
    { t: ts(22), src: "vm", level: "info", msg: "Win11-Client01: SPICE selected — integrated console requires VNC" },
    { t: ts(31), src: "console", level: "info", msg: "Right Ctrl pressed — input released from WS2022-DC01" },
    { t: ts(44), src: "agent", level: "info", msg: "NAS staging path /mnt/hypergery-nas/hypergery verified writable" },
  ];

  window.HG = { vms, labs, vmTemplates, labTemplates, hub, hosts, migrations, diagnostics, logs, HOST_LOCAL };
})();
