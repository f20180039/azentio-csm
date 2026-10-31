import type { SupportCall } from './api/support';
import { FeedbackVerdict, RefPrefix, TurnRole } from './vocab';

/** A YAML double-quoted scalar; JSON string escaping is valid YAML. */
const q = (s: string) => JSON.stringify(s);

function slug(id: string): string {
  return id.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 40) || 'call';
}

/**
 * The call as an eval scenario (backend/voice/eval/scenarios/README.md): each customer turn's words as `say`,
 * its intents and first verification as `expect`, reviewer corrections on the following agent turn as comments,
 * and outcome counts from the references the agent created.
 */
export function scenarioYaml(call: Pick<SupportCall, 'id' | 'outcome' | 'turns'>, title?: string): string {
  const out: string[] = [`id: reviewed-${slug(call.id)}`, `title: ${q(title ?? `Reviewed call ${call.id}`)}`, 'turns:'];
  let verified = false;
  const turns = call.turns;
  let said = 0;
  turns.forEach((t, i) => {
    if (t.role !== TurnRole.CUSTOMER || t.meta.no_speech || !t.text.trim()) return;
    said += 1;
    out.push(`  - say: ${q(t.text.trim())}`);
    const expect: string[] = [];
    const intents = t.meta.intents ?? [];
    if (intents.length) expect.push(`intents: [${intents.join(', ')}]`);
    if (t.meta.verified && !verified) {
      expect.push('verified: true');
      verified = true;
    }
    if (expect.length) out.push(`    expect: {${expect.join(', ')}}`);
    const reply = turns.slice(i + 1).find((x) => x.role === TurnRole.AGENT);
    reply?.feedback
      ?.filter((f) => f.verdict === FeedbackVerdict.BAD && f.correction)
      .forEach((f) => out.push(`    # reviewer (${f.author}) says it should have said: ${f.correction!.replace(/\s+/g, ' ')}`));
  });
  if (!said) out.push('  []');
  const refs = new Set(turns.flatMap((t) => t.meta.refs ?? []));
  const count = (p: RefPrefix) => [...refs].filter((r) => r.startsWith(p)).length;
  out.push(
    `outcome: {tickets: ${count(RefPrefix.TICKET)}, complaints: ${count(RefPrefix.COMPLAINT)}, routed: ${count(RefPrefix.ROUTED)}, escalations: ${count(RefPrefix.ESCALATION)}}`,
  );
  return out.join('\n') + '\n';
}
