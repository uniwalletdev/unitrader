/**
 * Copy for "how to get API keys" — Alpaca, Binance, Kraken, OANDA only.
 * Coinbase keeps bespoke UI in connect/settings; no entry here.
 */

export type GuidedExchangeId = "alpaca" | "binance" | "kraken" | "oanda";

export interface ExchangeApiKeyGuideData {
  id: GuidedExchangeId;
  title: string;
  steps: string[];
  apiPortalUrl: string;
  apiPortalLabel: string;
  permissionsNote?: string;
  extraNote?: string;
}

const GUIDES: Record<GuidedExchangeId, ExchangeApiKeyGuideData> = {
  alpaca: {
    id: "alpaca",
    title: "How to get your Alpaca API keys",
    steps: [
      "Log in at Alpaca (paper or live — generate keys on the environment you use).",
      "Open your dashboard → API Keys (or Paper Trading → API Keys for paper).",
      "Create a new key pair and copy the API Key ID and Secret Key immediately (the secret is shown once).",
    ],
    apiPortalUrl: "https://app.alpaca.markets/paper/dashboard/overview",
    apiPortalLabel: "Open Alpaca API keys",
    permissionsNote: "Use keys with trading enabled. Paper keys only work against the paper API.",
  },
  binance: {
    id: "binance",
    title: "How to get your Binance API keys",
    steps: [
      "Log in to Binance and open your profile → API Management (or Binance app equivalent).",
      "Create a new API key and complete any security steps (2FA, email).",
      "Copy the API Key and Secret Key into Unitrader.",
    ],
    apiPortalUrl: "https://www.binance.com/en/my/settings/api-management",
    apiPortalLabel: "Open Binance API management",
    permissionsNote: "Enable Spot trading if prompted. Do not enable Withdraw for bot use.",
    extraNote: "If you use Binance testnet, create keys on testnet and set the server testnet base URL.",
  },
  kraken: {
    id: "kraken",
    title: "How to get your Kraken API keys",
    steps: [
      "Log in to Kraken → Settings → API (or Create API key in the security area).",
      "Create a key with permissions needed for trading (and query if you want balances).",
      "Copy the API Key and the Private Key (often shown base64-encoded) — paste both here.",
    ],
    apiPortalUrl: "https://www.kraken.com/u/security/api",
    apiPortalLabel: "Open Kraken API settings",
    permissionsNote: "Restrict permissions: trading + funds query; avoid withdrawal rights for automated trading.",
    extraNote: "Kraken shows a one-time private key — Unitrader encrypts it after you connect.",
  },
  oanda: {
    id: "oanda",
    title: "How to get your OANDA credentials",
    steps: [
      "Log in to the OANDA portal for your account (practice or live).",
      "Open Manage API Access (or My Services → API) and generate a personal access token.",
      "Copy the token into API Token and your Account ID (e.g. 001-001-…) into Account ID.",
    ],
    apiPortalUrl: "https://www.oanda.com/account/tpa/personal_token",
    apiPortalLabel: "Open OANDA API access",
    permissionsNote: "Practice and live accounts have different tokens — use the one that matches your account.",
  },
};

export function getExchangeApiKeyGuide(
  exchangeId: string,
): ExchangeApiKeyGuideData | null {
  if (exchangeId === "coinbase") return null;
  const id = exchangeId.toLowerCase() as GuidedExchangeId;
  return GUIDES[id] ?? null;
}
