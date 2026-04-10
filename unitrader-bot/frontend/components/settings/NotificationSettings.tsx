import { Send } from "lucide-react";

export type TelegramLinkInfo = { bot: string; code: string } | null;
export type WhatsAppLinkInfo = { number: string; code: string } | null;

export function NotificationSettings(props: {
  telegramLinked: boolean;
  /** Telegram @handle without leading @, when known */
  telegramUsername: string | null;
  telegramNotificationsEnabled: boolean;
  onToggleTelegram: (next: boolean) => Promise<void>;
  onConnectTelegram: () => Promise<void>;
  telegramLinkInfo: TelegramLinkInfo;
  botUsername: string | null;

  whatsappLinked: boolean;
  /** E.164 phone from linked account, when known */
  whatsappNumber: string | null;
  whatsappNotificationsEnabled: boolean;
  onToggleWhatsApp: (next: boolean) => Promise<void>;
  onConnectWhatsApp: () => Promise<void>;
  whatsappLinkInfo: WhatsAppLinkInfo;

  linkingInProgress: boolean;

  signalNotifyMinConfidence: number;
  onChangeSignalNotifyMinConfidence: (next: number) => Promise<void>;
}) {
  const deepLinkBot = props.botUsername ? `https://t.me/${props.botUsername}?start=notify` : null;

  return (
    <div className="rounded-xl border border-dark-800 p-4">
      <p className="mb-3 text-sm font-medium text-white">Signal notifications</p>

      <div className="mb-3 rounded-lg border border-brand-500/20 bg-brand-500/[0.05] p-3">
        <p className="text-xs leading-relaxed text-dark-300">
          Signal alerts are available on all plans — free and Pro.
        </p>
      </div>

      <div className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Send size={14} className="text-sky-400" />
            <div>
              <p className="text-sm text-white">Telegram alerts</p>
              {props.telegramLinked ? (
                <p className="text-xs text-emerald-400/90">
                  {props.telegramUsername
                    ? `Connected as @${props.telegramUsername}`
                    : "Connected — no public @username on this Telegram account"}
                </p>
              ) : (
                <p className="text-xs text-dark-500">Not connected — connect to receive signal alerts.</p>
              )}
              {props.telegramLinked && (
                <p className="text-xs text-dark-500">Unitrader can alert you on Telegram.</p>
              )}
              {deepLinkBot && (
                <a
                  className="mt-1 inline-block text-xs text-brand-400 hover:text-brand-300"
                  href={deepLinkBot}
                  target="_blank"
                  rel="noreferrer"
                >
                  Connect via Telegram bot →
                </a>
              )}
            </div>
          </div>

          {props.telegramLinked ? (
            <input
              type="checkbox"
              checked={props.telegramNotificationsEnabled}
              onChange={(e) => props.onToggleTelegram(e.target.checked)}
            />
          ) : (
            <div className="flex flex-col items-end gap-2">
              <button
                type="button"
                disabled={props.linkingInProgress}
                onClick={props.onConnectTelegram}
                className="rounded-lg border border-dark-700 px-3 py-1.5 text-xs text-brand-400 disabled:opacity-50"
              >
                Connect Telegram
              </button>

              {props.telegramLinkInfo && (
                <div className="w-56 rounded-lg border border-dark-700 bg-dark-900 p-3 text-xs">
                  <p className="mb-1 text-dark-400">
                    If the bot didn&apos;t auto-connect, send this in chat:
                  </p>
                  <p className="select-all font-mono text-sm text-brand-400">/link {props.telegramLinkInfo.code}</p>
                  <p className="mt-1 text-dark-500">Code expires in 15 min</p>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Send size={14} className="text-emerald-400" />
            <div>
              <p className="text-sm text-white">WhatsApp alerts</p>
              {props.whatsappLinked ? (
                <p className="text-xs text-emerald-400/90">
                  {props.whatsappNumber
                    ? `Connected — ${props.whatsappNumber}`
                    : "Connected"}
                </p>
              ) : (
                <p className="text-xs text-dark-500">Not connected — connect to receive signal alerts.</p>
              )}
              {props.whatsappLinked && (
                <p className="text-xs text-dark-500">Unitrader can alert you on WhatsApp.</p>
              )}
            </div>
          </div>

          {props.whatsappLinked ? (
            <input
              type="checkbox"
              checked={props.whatsappNotificationsEnabled}
              onChange={(e) => props.onToggleWhatsApp(e.target.checked)}
            />
          ) : (
            <div className="flex flex-col items-end gap-2">
              <button
                type="button"
                disabled={props.linkingInProgress}
                onClick={props.onConnectWhatsApp}
                className="rounded-lg border border-dark-700 px-3 py-1.5 text-xs text-brand-400 disabled:opacity-50"
              >
                Connect WhatsApp
              </button>
              {props.whatsappLinkInfo && (
                <div className="w-56 rounded-lg border border-dark-700 bg-dark-900 p-3 text-xs">
                  <p className="mb-1 text-dark-400">Send this to {props.whatsappLinkInfo.number}:</p>
                  <p className="select-all font-mono text-sm text-brand-400">LINK {props.whatsappLinkInfo.code}</p>
                  <p className="mt-1 text-dark-500">Code expires in 15 min</p>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="rounded-lg border border-dark-800 bg-dark-950/30 p-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-sm text-white">
                Only alert me when confidence ≥ {props.signalNotifyMinConfidence}%
              </p>
              <p className="text-xs text-dark-500">This applies to both Telegram and WhatsApp.</p>
            </div>
          </div>
          <input
            type="range"
            min={50}
            max={100}
            step={1}
            value={props.signalNotifyMinConfidence}
            onChange={(e) => props.onChangeSignalNotifyMinConfidence(Number(e.target.value))}
            className="mt-3 w-full"
          />
        </div>
      </div>
    </div>
  );
}

