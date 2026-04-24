"use client";

/**
 * EtoroOfferCard.tsx — One-time dismissible banner on /trade that offers
 * eToro to post-onboarding users who haven't connected any exchange.
 *
 * Copy, environment ("demo" | "real") and gate logic are decided
 * server-side by GET /api/etoro/offer-card. The frontend just renders the
 * payload and routes Accept → ExchangeConnectWizard (with presetEnvironment,
 * openedFromApex=true) and Dismiss → POST /offer-card/dismiss.
 *
 * Never hardcodes "Apex" — the headline/body already have the user's chosen
 * ai_name substituted by the server.
 */

import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { etoroOfferApi, type EtoroOfferCard as CardPayload } from "@/lib/api";
import { trackEvent } from "@/lib/telemetry";
import ExchangeConnectWizard from "@/components/settings/ExchangeConnectWizard";

type VisibleCard = Extract<CardPayload, { show: true }>;

export default function EtoroOfferCard() {
  const [card, setCard] = useState<VisibleCard | null>(null);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [hidden, setHidden] = useState(false);
  const shownFiredRef = useRef(false);

  // ── Fetch once on mount ───────────────────────────────────────────────────
  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const res = await etoroOfferApi.get();
        if (!mounted) return;
        if (res.data?.show) {
          setCard(res.data);
        }
      } catch {
        // Non-fatal — banner simply stays hidden if the endpoint errors.
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  // ── Fire "shown" telemetry exactly once when the card first appears ───────
  useEffect(() => {
    if (!card || shownFiredRef.current) return;
    shownFiredRef.current = true;
    trackEvent("etoro_offer_card_shown", {
      trader_class: card.trader_class,
      environment: card.environment,
    });
  }, [card]);

  if (!card || hidden) return null;

  const handleAccept = () => {
    trackEvent("etoro_offer_card_accepted", {
      trader_class: card.trader_class,
      environment: card.environment,
    });
    setWizardOpen(true);
  };

  const handleDismiss = async () => {
    trackEvent("etoro_offer_card_dismissed", {
      trader_class: card.trader_class,
      environment: card.environment,
    });
    setHidden(true);
    try {
      await etoroOfferApi.dismiss();
    } catch {
      // Non-fatal — next page load will just re-fetch and hide if row updated.
    }
  };

  const handleWizardClose = async () => {
    setWizardOpen(false);
    setHidden(true);
    // Also persist dismissal so the card never reappears after Accept, even
    // if the user closed the wizard without completing the connection.
    try {
      await etoroOfferApi.dismiss();
    } catch {
      /* non-fatal */
    }
  };

  const handleWizardSuccess = async () => {
    setWizardOpen(false);
    setHidden(true);
    try {
      await etoroOfferApi.dismiss();
    } catch {
      /* non-fatal */
    }
  };

  return (
    <>
      <div className="mb-4 rounded-2xl border border-brand-500/30 bg-gradient-to-r from-brand-500/10 to-dark-900 p-4 md:p-5">
        <div className="flex items-start gap-3">
          <div className="flex-1 min-w-0">
            <div className="text-sm font-semibold text-white">
              {card.headline}
            </div>
            <p className="mt-1 text-xs leading-relaxed text-dark-300">
              {card.body}
            </p>
            <div className="mt-3 flex items-center gap-3">
              <button
                type="button"
                onClick={handleAccept}
                className="rounded-lg bg-brand-500 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-brand-400 active:scale-[0.98]"
              >
                {card.cta}
              </button>
              <span className="text-[11px] uppercase tracking-wide text-dark-500">
                {card.environment === "demo" ? "Practice mode" : "Real money"}
              </span>
            </div>
          </div>
          <button
            type="button"
            onClick={handleDismiss}
            aria-label="Dismiss eToro offer"
            className="-mr-1 -mt-1 rounded-md p-1 text-dark-500 transition hover:bg-dark-800 hover:text-dark-200"
          >
            <X size={16} />
          </button>
        </div>
      </div>

      {wizardOpen && (
        <ExchangeConnectWizard
          exchange="etoro"
          presetEnvironment={card.environment}
          openedFromApex={true}
          onSuccess={handleWizardSuccess}
          onClose={handleWizardClose}
        />
      )}
    </>
  );
}
