const fs = require('node:fs');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { spawn } = require('node:child_process');

function fail(message) {
  console.error(`dual-claude: ${message}`);
  process.exit(2);
}
function readSettings(file, required) {
  if (!fs.existsSync(file)) {
    if (required) fail('Missing CC Switch settings.json. Configure its dedicated directory first.');
    return {};
  }
  let value;
  try { value = JSON.parse(fs.readFileSync(file, 'utf8')); }
  catch { fail('Cannot read settings JSON; contents omitted.'); }
  if (!value || typeof value !== 'object' || Array.isArray(value)) fail('Settings must be a JSON object.');
  const env = value.env ?? {};
  if (!env || typeof env !== 'object' || Array.isArray(env) || Object.values(env).some(v => typeof v !== 'string')) {
    fail('Settings env must contain string values.');
  }
  return value;
}
function routingKey(key) {
  return /^(ANTHROPIC_|CLAUDE_CODE_USE_|CLAUDE_CODE_OAUTH_)/.test(key)
    || ['CLAUDE_CONFIG_DIR', 'CLAUDE_CODE_BASE_URL', 'CLAUDE_CODE_API_KEY_HELPER', 'CLAUDE_CODE_SESSION_ACCESS_TOKEN'].includes(key);
}

const config = process.env.CLAUDE_CONFIG_DIR;
if (!config || !path.isAbsolute(config)) fail('CLAUDE_CONFIG_DIR must be an absolute path.');
const source = process.env.CC_CONFIG_SOURCE;
let settings = readSettings(path.join(source || config, 'settings.json'), Boolean(source));
if (source) {
  let url;
  try { url = new URL(settings.env?.ANTHROPIC_BASE_URL); }
  catch { fail('Third-party settings require a valid ANTHROPIC_BASE_URL.'); }
  if (!['http:', 'https:'].includes(url.protocol) || url.hostname.toLowerCase().replace(/\.$/, '') === 'api.anthropic.com') {
    fail('Expected a third-party HTTP(S) endpoint.');
  }
  if (url.username || url.password || url.search || url.hash) fail('Do not put credentials in endpoint URLs.');
  if (!settings.env.ANTHROPIC_AUTH_TOKEN && !settings.env.ANTHROPIC_API_KEY && !settings.apiKeyHelper) {
    fail('Third-party credentials or apiKeyHelper are missing.');
  }
  if (['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)) {
    if (!process.env.CC_PROXY_BASE_URL) {
      fail('Host loopback proxy detected. Verify the listener, then set CC_PROXY_BASE_URL, e.g. http://host.docker.internal:15721.');
    }
    let replacement;
    try { replacement = new URL(process.env.CC_PROXY_BASE_URL); }
    catch { fail('CC_PROXY_BASE_URL is invalid.'); }
    if (!['http:', 'https:'].includes(replacement.protocol) || replacement.username || replacement.password || replacement.search || replacement.hash) {
      fail('CC_PROXY_BASE_URL must be an HTTP(S) endpoint without credentials.');
    }
    if (['127.0.0.1', 'localhost', '[::1]'].includes(replacement.hostname)) fail('CC_PROXY_BASE_URL still points to container loopback.');
    settings.env.ANTHROPIC_BASE_URL = replacement.href.replace(/\/$/, '');
  }
  try {
    fs.mkdirSync(config, { recursive: true, mode: 0o700 });
    const temp = path.join(config, `.settings-${randomUUID()}.tmp`);
    try {
      fs.writeFileSync(temp, JSON.stringify(settings, null, 2) + '\n', { mode: 0o600, flag: 'wx' });
      fs.renameSync(temp, path.join(config, 'settings.json'));
    } finally {
      if (fs.existsSync(temp)) fs.unlinkSync(temp);
    }
  } catch { fail('Cannot write the container profile configuration.'); }
} else if (settings.apiKeyHelper || Object.entries(settings.env || {}).some(([key, value]) => value && routingKey(key))) {
  fail('Official container settings contain routing/auth overrides; review its configuration volume.');
}

const defaults = ['--setting-sources', 'user'];
if (source && !settings.model && settings.env?.ANTHROPIC_DEFAULT_SONNET_MODEL) defaults.push('--model', 'sonnet');
const child = spawn('claude', [...defaults, ...process.argv.slice(2)], { stdio: 'inherit' });
for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => child.kill(sig));
child.on('error', () => fail('Could not start the Claude CLI.'));
child.on('exit', (code, sig) => process.exit(sig === 'SIGINT' ? 130 : sig ? 143 : code ?? 1));
