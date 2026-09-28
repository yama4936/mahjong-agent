import { spawnSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

/** Use OS-trusted roots on older Node versions without disabling TLS checks. */
export function windowsCaEnvironment(root, environment = process.env) {
  const env = { ...environment };
  if (process.platform !== "win32" || env.NODE_EXTRA_CA_CERTS) return env;
  const command = "$ErrorActionPreference = 'Stop'; foreach ($location in @('CurrentUser', 'LocalMachine')) { $store = New-Object System.Security.Cryptography.X509Certificates.X509Store('Root', $location); try { $store.Open('ReadOnly'); foreach ($cert in $store.Certificates) { [Console]::WriteLine([Convert]::ToBase64String($cert.RawData)) } } finally { $store.Close() } }";
  const result = spawnSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", command], {
    encoding: "utf8", windowsHide: true, timeout: 10000,
  });
  if (result.error || result.status !== 0) throw new Error("Unable to load Windows trusted certificate roots");
  const certificates = result.stdout.trim().split(/\r?\n/).filter(Boolean);
  if (!certificates.length || certificates.some((value) => !/^[A-Za-z0-9+/]+=*$/.test(value))) {
    throw new Error("Invalid Windows trusted certificate export");
  }
  const directory = path.join(root, ".runtime");
  mkdirSync(directory, { recursive: true });
  const bundle = path.join(directory, "windows-trusted-roots.pem");
  writeFileSync(bundle, certificates.map((value) =>
    `-----BEGIN CERTIFICATE-----\n${value.match(/.{1,64}/g).join("\n")}\n-----END CERTIFICATE-----\n`
  ).join(""));
  env.NODE_EXTRA_CA_CERTS = bundle;
  return env;
}
