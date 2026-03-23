import { useState } from "react";
import Link from "next/link";
import LegalLayout from "../components/legal/LegalLayout";

type FAQItem = {
  question: string;
  answer: string;
};

const FAQ_ITEMS: FAQItem[] = [
  {
    question: "Is my money safe with Unitrader?",
    answer:
      "Your money never touches Unitrader. Apex trades through your own Alpaca or Coinbase account. Universal Wallet Ltd never holds, controls, or has access to your funds. Your money sits with regulated exchanges (Alpaca is FINRA-registered, Coinbase is FCA-registered) at all times.",
  },
  {
    question: "What does Apex actually do?",
    answer:
      "Apex is an AI that analyses market data — including price movements, technical indicators (RSI, MACD), and news sentiment — and places trades through your exchange account when it finds a high-confidence signal. You set the parameters. You can pause Apex at any time.",
  },
  {
    question: "What if Apex makes a bad trade?",
    answer:
      "Every trade has a stop-loss set automatically to limit losses. You can also pause Apex at any time from the app or by sending /pause to the Telegram bot. Trading involves risk — please read our Risk Disclosure before trading with real money.",
  },
  {
    question: "How do I connect my exchange account?",
    answer:
      "Go to Settings → Connected Accounts. You will need an API key from your Alpaca or Coinbase account. We have a step-by-step guide in the Exchange Wizard. Your API key is encrypted and stored securely.",
  },
  {
    question: "Can I delete my account and all my data?",
    answer:
      "Yes. Go to Settings → Account → Delete Account. We will delete all your personal data within 30 days. Trade history is anonymised and retained for 7 years as required by HMRC. You can also email privacy@unitrader.ai.",
  },
  {
    question: "Is Unitrader regulated by the FCA?",
    answer:
      "Universal Wallet Ltd is not FCA-regulated. Unitrader is a software tool, not a financial broker or investment advisor. The exchanges we connect to (Alpaca, Coinbase) are regulated in their respective jurisdictions. Please read our full Risk Disclosure before trading.",
  },
];

function Accordion({ question, answer }: FAQItem) {
  const [open, setOpen] = useState(false);

  return (
    <div
      style={{
        borderBottom: "1px solid #1e2330",
        paddingBottom: "12px",
        marginBottom: "4px",
      }}
    >
      <button
        onClick={() => setOpen((v) => !v)}
        style={{
          width: "100%",
          textAlign: "left",
          background: "none",
          border: "none",
          cursor: "pointer",
          padding: "12px 0",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: "12px",
        }}
      >
        <span style={{ fontSize: "14px", fontWeight: 600, color: "#e8eaed" }}>
          {question}
        </span>
        <span style={{ fontSize: "16px", color: "#6b7280", flexShrink: 0 }}>
          {open ? "−" : "+"}
        </span>
      </button>
      {open && (
        <p
          style={{
            fontSize: "14px",
            color: "#9ca3af",
            lineHeight: 1.75,
            marginBottom: "8px",
            paddingRight: "24px",
          }}
        >
          {answer}
        </p>
      )}
    </div>
  );
}

export default function SupportPage() {
  return (
    <LegalLayout title="Support" lastUpdated="March 2026">
      <h2>Get help with Unitrader</h2>

      <h3>Email support</h3>
      <p>
        For account issues, technical problems, or billing questions:
        <br />
        <strong>
          <a href="mailto:support@unitrader.ai">support@unitrader.ai</a>
        </strong>
        <br />
        We respond within 1 business day.
      </p>

      <h3>Common questions</h3>
      <div style={{ marginTop: "8px" }}>
        {FAQ_ITEMS.map((item) => (
          <Accordion key={item.question} question={item.question} answer={item.answer} />
        ))}
      </div>

      <h3>Legal and privacy</h3>
      <ul>
        <li>
          <Link href="/privacy">Privacy Policy</Link>
        </li>
        <li>
          <Link href="/terms">Terms of Service</Link>
        </li>
        <li>
          <Link href="/risk">Risk Disclosure</Link>
        </li>
        <li>ICO Registration: ZC068643</li>
      </ul>

      <h3>Company</h3>
      <p>
        Universal Wallet Ltd
        <br />
        128 City Road, London, United Kingdom, EC1V 2NX
        <br />
        Company No. 16695347
      </p>
    </LegalLayout>
  );
}
