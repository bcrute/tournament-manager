import { Link } from "react-router-dom";

/**
 * The page that exists instead of a cookie banner.
 *
 * There is no banner because there is nothing to consent to: no analytics, no
 * advertising, no third-party requests, and the only things stored are the ones
 * that make the thing you asked for work. That claim is only worth making if
 * it's checkable, so this page lists every single item rather than summarising.
 */
export default function Privacy() {
  return (
    <>
      <section className="hero">
        <h1>Privacy</h1>
        <p className="lede">
          No tracking, no advertising, no analytics, and no third-party requests. There is
          no cookie banner because there is nothing here to consent to.
        </p>
      </section>

      <section className="prose">
        <h2>What we store, and why</h2>
        <p>
          Everything below is needed to run the thing you asked for. Nothing is used to
          profile you, and nothing is shared.
        </p>

        <table className="privacy-table">
          <thead>
            <tr>
              <th>What</th>
              <th>Where</th>
              <th>Why</th>
              <th>How long</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Your seat in a game</td>
              <td>This device</td>
              <td>So a refresh, a locked screen or a dropped connection doesn&rsquo;t lose your place</td>
              <td>Until you leave the game</td>
            </tr>
            <tr>
              <td>Your seat in a tournament</td>
              <td>This device</td>
              <td>So each round opens your table without typing a code again</td>
              <td>Until you check in as someone else</td>
            </tr>
            <tr>
              <td>The display name you typed</td>
              <td>This device</td>
              <td>So you don&rsquo;t retype it at every game</td>
              <td>Until you change or clear it</td>
            </tr>
            <tr>
              <td>Language preference</td>
              <td>This device</td>
              <td>So the app opens in the language you picked</td>
              <td>Until you change it</td>
            </tr>
            <tr>
              <td>
                A sign-in cookie <em>(only if you make an account)</em>
              </td>
              <td>Cookie</td>
              <td>Keeps you signed in. It is httpOnly and Secure, so scripts can&rsquo;t read it</td>
              <td>90 days, or 30 days idle, or until you sign out</td>
            </tr>
            <tr>
              <td>
                A default table name <em>(only if you set one)</em>
              </td>
              <td>Your account</td>
              <td>
                So the name you play under follows you to any device you sign in from,
                instead of being retyped on each one
              </td>
              <td>Until you change or clear it</td>
            </tr>
          </tbody>
        </table>

        <h2>What we don&rsquo;t do</h2>
        <ul>
          <li>No analytics or telemetry of any kind.</li>
          <li>No advertising, and no data sold or shared.</li>
          <li>
            No third-party requests. No CDN, no hosted fonts, no embedded widgets — the
            page loads from this server and nowhere else.
          </li>
          <li>No location, no device fingerprinting, no contact list, no uploads.</li>
          <li>
            <strong>Playing needs no account at all.</strong> If you never make one, we
            hold no email, no password and no name beyond the one you type at the table.
          </li>
        </ul>

        <h2>Blocking things is fine</h2>
        <p>
          If your browser or an extension refuses local storage, the app still works. It
          simply can&rsquo;t remember your seat, so a refresh will ask you to rejoin the
          room. Nothing breaks, and nothing nags you about it.
        </p>

        <h2>Addresses</h2>
        <p>
          Rate limiting and abuse blocking need to tell one visitor from another. We never
          store an IP address: it&rsquo;s hashed with a secret salt, and only that hash is
          kept, for thirty days. That is pseudonymous rather than anonymous — a known
          address could be checked against a hash — so we treat it carefully and keep it
          briefly.
        </p>

        <h2>Deleting your account</h2>
        <p>
          If you made one, you can delete it from{" "}
          <Link to="/account/settings">your account settings</Link>. That erases the account, its
          notes and its recovery codes. Games you played in stay, unlinked from you —
          deleting them would punch holes in other players&rsquo; history and in
          organizers&rsquo; standings.
        </p>
      </section>
    </>
  );
}
