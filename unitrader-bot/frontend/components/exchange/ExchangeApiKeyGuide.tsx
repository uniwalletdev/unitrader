import { ExternalLink } from "lucide-react";
import type { ExchangeApiKeyGuideData } from "@/lib/exchangeApiKeyGuides";

type Props = {
  guide: ExchangeApiKeyGuideData;
};

/**
 * Collapsible broker-specific steps + portal CTA.
 * Mobile: full-width CTA, readable step text, comfortable summary tap target.
 */
export default function ExchangeApiKeyGuide({ guide }: Props) {
  return (
    <div className="rounded-xl border border-dark-800 bg-dark-900/30">
      <details className="group">
        <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 px-3 py-2.5 text-xs font-medium text-dark-300 transition-colors hover:text-white sm:min-h-0 sm:py-2 [&::-webkit-details-marker]:hidden">
          <span className="select-none text-brand-400">▸</span>
          <span className="flex-1 leading-snug">{guide.title}</span>
        </summary>
        <div className="border-t border-dark-800/80 px-3 pb-3 pt-2">
          <ol className="list-decimal space-y-2 pl-4 text-xs leading-relaxed text-dark-400 marker:text-dark-500">
            {guide.steps.map((step, i) => (
              <li key={i} className="break-words pl-0.5">
                {step}
              </li>
            ))}
          </ol>

          <a
            href={guide.apiPortalUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="btn-outline mt-3 flex w-full min-h-11 items-center justify-center gap-2 text-xs sm:min-h-0 sm:w-auto sm:justify-center"
          >
            {guide.apiPortalLabel}
            <ExternalLink size={14} className="shrink-0 opacity-80" aria-hidden />
          </a>

          {guide.permissionsNote ? (
            <p className="mt-2 text-[11px] leading-relaxed text-dark-500 sm:text-xs">
              <span className="font-medium text-dark-400">Tip: </span>
              {guide.permissionsNote}
            </p>
          ) : null}
          {guide.extraNote ? (
            <p className="mt-1.5 text-[11px] leading-relaxed text-dark-600 sm:text-xs">{guide.extraNote}</p>
          ) : null}
        </div>
      </details>
    </div>
  );
}
