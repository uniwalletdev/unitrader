import LegalLayout from "../components/legal/LegalLayout";

export default function TermsPage() {
  return (
    <LegalLayout title="Terms of Service" lastUpdated="March 2026">
      <p>
        By creating an account, you agree to these Terms. Please read them carefully.
      </p>

      <h2>1. About Unitrader and Universal Wallet Ltd</h2>
      <p>
        Unitrader is operated by Universal Wallet Ltd, registered in England and Wales (Company No.
        16695347), 128 City Road, London, EC1V 2NX.
      </p>
      <p>
        Unitrader is a <strong>software tool</strong> that provides AI-powered trading analysis and
        automated trade execution through your own exchange accounts. Unitrader is{" "}
        <strong>not</strong> a financial broker, investment firm, or financial advisor. Unitrader is{" "}
        <strong>not</strong> regulated by the Financial Conduct Authority (FCA).
      </p>

      <h2>2. Nature of the service — important</h2>
      <p>
        <strong>Not financial advice:</strong> Nothing Apex says or executes constitutes financial
        advice or investment advice. All Apex outputs are automated analysis from a software tool.
      </p>
      <p>
        <strong>Your responsibility:</strong> All trading decisions made through Unitrader are
        ultimately your responsibility. You can pause Apex, adjust parameters, or close positions
        at any time.
      </p>
      <p>
        <strong>Your exchange account:</strong> Your funds remain in your exchange account at all
        times. Universal Wallet Ltd never holds, controls, or has access to your funds. We cannot
        move, withdraw, or transfer your money.
      </p>
      <p>
        <strong>AI limitations:</strong> Apex may make incorrect analyses, miss market events, fail
        to execute trades due to technical issues, or perform differently to historical simulations.
        You acknowledge these limitations.
      </p>

      <h2>3. Risk warnings</h2>
      <ul>
        <li>
          <strong>Capital at risk:</strong> You may lose some or all of the money you invest.
        </li>
        <li>
          <strong>No guaranteed returns:</strong> Past performance is not a reliable indicator of
          future results.
        </li>
        <li>
          <strong>Stop-losses not guaranteed:</strong> In fast-moving markets, positions may close
          at a worse price than your stop-loss level.
        </li>
        <li>
          <strong>Technology risk:</strong> Technical failures may prevent trades from executing as
          expected.
        </li>
      </ul>

      <h2>4. Your obligations</h2>
      <ul>
        <li>You must be at least 18 years old.</li>
        <li>You must provide accurate account information.</li>
        <li>
          You are responsible for the security of your login credentials and API keys.
        </li>
        <li>
          You must not use Unitrader for unlawful purposes including market manipulation, money
          laundering, or tax evasion.
        </li>
        <li>You must comply with the terms of any exchange account you connect.</li>
      </ul>

      <h2>5. Limitation of liability</h2>
      <p>
        To the maximum extent permitted by law, Universal Wallet Ltd&apos;s total liability for any
        claim shall not exceed the subscription fees you have paid in the 12 months preceding the
        claim.
      </p>
      <p>
        Universal Wallet Ltd is not liable for: trading losses, loss of profits, loss of data,
        indirect or consequential losses, losses from third-party exchange failures, or losses from
        your failure to monitor your account.
      </p>
      <p>
        Nothing limits liability for fraud, death, or personal injury caused by negligence, or any
        liability that cannot be limited by law.
      </p>

      <h2>6. Subscriptions and payment</h2>
      <p>
        Subscriptions are processed by Stripe. Subscriptions auto-renew unless cancelled before
        the renewal date. Refunds are at our discretion — contact{" "}
        <a href="mailto:support@unitrader.ai">support@unitrader.ai</a>.
      </p>

      <h2>7. Termination</h2>
      <p>
        You may close your account at any time by contacting{" "}
        <a href="mailto:support@unitrader.ai">support@unitrader.ai</a>. On termination, Apex will
        cease trading. You remain responsible for any open positions. Trade history and audit logs
        are retained for 7 years after closure.
      </p>

      <h2>8. Governing law</h2>
      <p>
        These Terms are governed by the laws of England and Wales. Disputes will be resolved in
        the courts of England and Wales.
      </p>

      <h2>9. Contact</h2>
      <p>
        Universal Wallet Ltd | Company No. 16695347
        <br />
        128 City Road, London, United Kingdom, EC1V 2NX
        <br />
        <a href="mailto:support@unitrader.ai">support@unitrader.ai</a> |{" "}
        <a href="mailto:legal@unitrader.ai">legal@unitrader.ai</a>
      </p>
    </LegalLayout>
  );
}
