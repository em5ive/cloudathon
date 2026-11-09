// Public Cognito client: authorization code + PKCE, no client secret.
export function base64url(bytes) {
  return btoa(String.fromCharCode(...bytes)).replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', '');
}

export async function makeLogin(config, storage = sessionStorage) {
  const verifier = base64url(crypto.getRandomValues(new Uint8Array(48)));
  const state = base64url(crypto.getRandomValues(new Uint8Array(32)));
  const challenge = base64url(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))));
  storage.setItem('anyco.pkce', JSON.stringify({verifier, state, created: Date.now()}));
  const url = new URL('/oauth2/authorize', config.cognitoDomain);
  url.search = new URLSearchParams({client_id: config.clientId, response_type: 'code', scope: 'openid email', redirect_uri: config.redirectUri, state, code_challenge_method: 'S256', code_challenge: challenge});
  return url.href;
}

export function consumePkce(state, storage = sessionStorage) {
  const pending = JSON.parse(storage.getItem('anyco.pkce') || 'null');
  storage.removeItem('anyco.pkce');
  if (!pending || !state || pending.state !== state || Date.now() - pending.created > 600000 || pending.created > Date.now()) {
    throw new Error('Your sign-in session expired. Please sign in again.');
  }
  return pending.verifier;
}

export async function redeemCode(config, code, state) {
  const verifier = consumePkce(state);
  const response = await fetch(new URL('/oauth2/token', config.cognitoDomain), {
    method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'},
    body: new URLSearchParams({grant_type: 'authorization_code', client_id: config.clientId, code, code_verifier: verifier, redirect_uri: config.redirectUri}),
    cache: 'no-store', credentials: 'omit',
  });
  if (!response.ok) throw new Error('Sign-in could not be completed. Please try again.');
  const tokens = await response.json();
  if (!tokens.access_token || !Number.isFinite(tokens.expires_in)) throw new Error('Invalid sign-in response.');
  // Keep access token only in memory; discard ID and refresh tokens.
  return {accessToken: tokens.access_token, expires: Date.now() + tokens.expires_in * 1000};
}
