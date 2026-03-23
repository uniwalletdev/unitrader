import LegalLayout from "../components/legal/LegalLayout";

export default function PrivacyPage() {
  return (
    <LegalLayout title="Privacy Policy" lastUpdated="March 2026">
      <h2>Who we are</h2>
      <p>
        Unitrader is a product of Universal Wallet Ltd, a company registered in England and Wales
        (Company No. 16695347). We are registered with the Information Commissioner&apos;s Office as
        a data controller (ICO Ref: ZC068643).
      </p>
      <p>
        <strong>Registered address:</strong> 128 City Road, London, United Kingdom, EC1V 2NX
        <br />
        <strong>Contact:</strong>{" "}
        <a href="mailto:privacy@unitrader.ai">privacy@unitrader.ai</a>
      </p>

      <h2>What data we collect and why</h2>
      <p>
        <strong>Account data</strong> (name, email, password hash) — to provide your account.
        Legal basis: contract performance.
      </p>
      <p>
        <strong>Exchange API keys</strong> (Alpaca, Coinbase, OANDA) — to execute trades on your
        behalf. Legal basis: contract performance. All keys are encrypted at rest. We only use your
        keys to place trades you authorise. We never transfer funds, withdraw money, or use your
        keys for any other purpose.
      </p>
      <p>
        <strong>Trading data</strong> (trade history, positions, P&amp;L) — to provide the service
        and improve Apex. Legal basis: contract performance and legitimate interests.
      </p>
      <p>
        <strong>Chat and onboarding messages</strong> — to personalise your Apex experience. Legal
        basis: contract performance.
      </p>
      <p>
        <strong>Payment data</strong> — handled entirely by Stripe. We never store card numbers.
      </p>
      <p>
        <strong>Usage and device data</strong> (IP address, browser, device type) — for security
        and fraud prevention. Legal basis: legitimate interests.
      </p>

      <h2>How we share your data</h2>
      <p>We share data only with these third-party services to operate Unitrader:</p>
      <ul>
        <li>
          <strong>Anthropic</strong> — AI analysis via Claude API. Your trade context is sent to
          generate Apex&apos;s responses.
        </li>
        <li>
          <strong>Clerk</strong> — authentication and account management.
        </li>
        <li>
          <strong>Stripe</strong> — payment processing.
        </li>
        <li>
          <strong>Alpaca Markets</strong> — stock trade execution. Your API key places orders.
        </li>
        <li>
          <strong>Coinbase</strong> — crypto trade execution. Your API key places orders.
        </li>
        <li>
          <strong>OANDA</strong> — forex trade execution. Your API key places orders.
        </li>
        <li>
          <strong>Railway</strong> — cloud hosting for our backend.
        </li>
        <li>
          <strong>Supabase</strong> — database. Data stored in the EU/UK.
        </li>
        <li>
          <strong>Resend</strong> — transactional email.
        </li>
        <li>
          <strong>Telegram / Twilio</strong> — notifications if you connect these services.
        </li>
      </ul>
      <p>We do not sell your data. We do not use your data for advertising.</p>

      <h2>How long we keep your data</h2>
      <ul>
        <li>Account data: active period + 30 days after deletion</li>
        <li>Trade history and audit logs: 7 years (HMRC requirement)</li>
        <li>Chat history: 12 months</li>
        <li>Payment records: 7 years (legal requirement)</li>
      </ul>

      <h2>Your rights under UK GDPR</h2>
      <p>
        You have the right to access, correct, delete, or export your personal data. To exercise
        any right, email <a href="mailto:privacy@unitrader.ai">privacy@unitrader.ai</a>. We respond
        within 30 days.
      </p>
      <p>
        Note: trade history and audit logs must be retained for 7 years by law. All other data is
        deleted within 30 days of a valid erasure request.
      </p>

      <h2>Security</h2>
      <p>
        We protect your data using encrypted API key storage, HTTPS on all connections, row-level
        security on all database tables, and automatic session expiry.
      </p>
      <p>
        If we experience a data breach affecting your personal data, we will notify you and the ICO
        within 72 hours as required by UK GDPR.
      </p>

      <h2>Cookies</h2>
      <p>
        We use essential cookies only: authentication cookies (Clerk) and security cookies (CSRF
        protection). We do not use advertising or tracking cookies.
      </p>

      <h2>Children</h2>
      <p>
        Unitrader is not intended for users under 18. Contact{" "}
        <a href="mailto:privacy@unitrader.ai">privacy@unitrader.ai</a> if you believe a child has
        provided us personal data.
      </p>

      <h2>Complaints</h2>
      <p>
        If you are unhappy with how we handle your data, you can complain to the ICO:{" "}
        <a href="https://ico.org.uk/make-a-complaint" target="_blank" rel="noopener noreferrer">
          ico.org.uk/make-a-complaint
        </a>{" "}
        | 0303 123 1113
      </p>
    </LegalLayout>
  );
}
