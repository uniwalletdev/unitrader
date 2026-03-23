import LegalLayout from "../components/legal/LegalLayout";

export default function RiskPage() {
  return (
    <LegalLayout title="Risk Disclosure" lastUpdated="March 2026">
      <p>
        <strong>Read this before trading with real money.</strong>
      </p>

      <h2>What Unitrader is</h2>
      <p>
        Unitrader is an AI-powered trading tool built by Universal Wallet Ltd. It analyses market data
        and executes trades through your own exchange account.
      </p>
      <p>
        Unitrader is <strong>not</strong> a financial advisor, fund manager, or FCA-regulated service.
        Nothing Unitrader says or does constitutes investment advice or a personal recommendation under
        UK law.
      </p>

      <h2>The risks you take when trading</h2>
      <p>
        <strong>You may lose money.</strong> Trading financial instruments involves significant risk
        of loss. You may lose some or all of the money you commit to trading. This risk is real and
        has occurred for users of this platform.
      </p>
      <p>
        <strong>Unitrader can be wrong.</strong> AI systems make mistakes. Market conditions change
        faster than any AI can react. Unitrader does not have access to all market information. A high
        confidence score does not guarantee a profitable trade.
      </p>
      <p>
        <strong>Past performance means nothing.</strong> The WhatIfSimulator and any historical
        results shown are based on historical market data. They do not predict future returns. Real
        future returns may be significantly lower or negative.
      </p>
      <p>
        <strong>Stop-losses are not guaranteed.</strong> In fast-moving or gapped markets, your
        position may close at a worse price than your stop-loss level.
      </p>
      <p>
        <strong>Technical failures can occur.</strong> If Unitrader, your exchange, or your
        internet connection fails, trades may not execute as expected.
      </p>

      <h2>Your money and your account</h2>
      <p>
        Your funds remain in your own exchange account (Alpaca, Coinbase, or OANDA) at all times.
        Universal Wallet Ltd never holds your funds and cannot move or withdraw your money.
      </p>

      <h2>FCA risk warning (required by UK law)</h2>
      <p>
        Trading financial instruments carries a high level of risk to your capital. You should only
        trade with money you can afford to lose entirely. Prices can move rapidly against you. Past
        performance is not a guide to future results.
      </p>

      <h2>Before you trade with real money</h2>
      <p>Ask yourself:</p>
      <ul>
        <li>Can I afford to lose this money entirely?</li>
        <li>Do I understand that Unitrader is a software tool, not a financial advisor?</li>
        <li>Have I read and understood the Terms of Service?</li>
        <li>Am I 18 years of age or older?</li>
      </ul>
      <p>
        If you answered no to any of these, do not trade with real money. Use paper trading (Watch
        Mode) until you are comfortable.
      </p>

      <h2>Contact</h2>
      <p>
        If you have questions about these risks:{" "}
        <a href="mailto:support@unitrader.ai">support@unitrader.ai</a>
      </p>
      <p>
        Universal Wallet Ltd | 128 City Road, London EC1V 2NX | Co. No. 16695347
      </p>
    </LegalLayout>
  );
}
