/**
 * Required attribution. The wording of the Wizards paragraph is fixed by their
 * Fan Content Policy and shouldn't be paraphrased.
 */
export default function FanContentNotice() {
  return (
    <aside className="fan-notice">
      <p>
        Table is unofficial Fan Content permitted under the Fan Content Policy. Not
        approved/endorsed by Wizards. Portions of the materials used are property of Wizards
        of the Coast. ©Wizards of the Coast LLC.
      </p>
      <p>
        The Treachery variant and its identity cards are the work of the{" "}
        <a href="https://mtgtreachery.net" target="_blank" rel="noreferrer">
          MTG Treachery
        </a>{" "}
        project. Identity card artwork belongs to the individual illustrators, who are
        credited on each card.
      </p>
    </aside>
  );
}
