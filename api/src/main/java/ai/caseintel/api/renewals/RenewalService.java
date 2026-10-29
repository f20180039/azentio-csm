package ai.caseintel.api.renewals;

import ai.caseintel.api.audit.AuditService;
import ai.caseintel.api.config.AppProperties;
import ai.caseintel.api.domain.CaseEntity;
import ai.caseintel.api.domain.CaseStatus;
import ai.caseintel.api.audit.AuditRow;
import ai.caseintel.api.renewals.RenewalDtos.CallEnded;
import ai.caseintel.api.renewals.RenewalDtos.CallView;
import ai.caseintel.api.renewals.RenewalDtos.HandoffQueued;
import ai.caseintel.api.renewals.RenewalDtos.HandoffRequest;
import ai.caseintel.api.renewals.RenewalDtos.Options;
import ai.caseintel.api.renewals.RenewalDtos.PaymentLinkSent;
import ai.caseintel.api.renewals.RenewalDtos.PolicyView;
import ai.caseintel.api.renewals.RenewalDtos.Quote;
import ai.caseintel.api.renewals.RenewalDtos.QuoteRequest;
import ai.caseintel.api.renewals.RenewalDtos.RemovableAddon;
import ai.caseintel.api.renewals.RenewalDtos.SummaryItem;
import ai.caseintel.api.renewals.RenewalDtos.TurnRequest;
import ai.caseintel.api.renewals.RenewalDtos.Verification;
import ai.caseintel.api.renewals.RenewalDtos.QueueItem;
import ai.caseintel.api.renewals.RenewalDtos.Risk;
import ai.caseintel.api.renewals.RenewalDtos.StartedCall;
import ai.caseintel.api.repo.CaseRepository;
import ai.caseintel.api.service.ApiException;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.Set;
import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.temporal.ChronoUnit;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class RenewalService {

    static final String CASE_TYPE = "renewal_call";
    private static final LocalTime CALLS_FROM = LocalTime.of(9, 0);
    private static final LocalTime CALLS_UNTIL = LocalTime.of(21, 0);

    private final PolicyRepository policies;
    private final CallRepository calls;
    private final CaseRepository cases;
    private final AuditService audit;
    private final Playbook playbook;
    private final Clock clock;
    private final AppProperties props;
    private final ObjectMapper mapper;

    public RenewalService(PolicyRepository policies, CallRepository calls, CaseRepository cases, AuditService audit,
                          Playbook playbook, Clock clock, AppProperties props, ObjectMapper mapper) {
        this.policies = policies;
        this.calls = calls;
        this.cases = cases;
        this.audit = audit;
        this.playbook = playbook;
        this.clock = clock;
        this.props = props;
        this.mapper = mapper;
    }

    @PreAuthorize("hasRole('ANALYST')")
    @Transactional(readOnly = true)
    public List<QueueItem> queue() {
        LocalDate today = LocalDate.now(clock);
        return policies.findAll().stream()
                .filter(p -> !p.getExpiresOn().isBefore(today))
                .map(p -> {
                    Risk r = LapseRisk.assess(p, today);
                    return new QueueItem(p.getId(), p.getHolderName(), p.getProduct(), p.getExpiresOn(),
                            (int) ChronoUnit.DAYS.between(today, p.getExpiresOn()), r.score(), r.signals(), r.route());
                })
                .sorted(Comparator.comparing(QueueItem::score).reversed().thenComparingInt(QueueItem::daysToExpiry))
                .toList();
    }

    @PreAuthorize("hasRole('ANALYST')")
    @Transactional
    public StartedCall startCall(String policyId, String actor) {
        if (policyId == null || policyId.isBlank()) {
            throw ApiException.badRequest("policyId is required");
        }
        PolicyEntity p = policies.findById(policyId)
                .orElseThrow(() -> ApiException.notFound("Policy " + policyId + " not found"));
        if (p.isOpenComplaint()) {
            throw ApiException.conflict("HUMAN_ONLY");
        }
        if (p.isDoNotCall()) {
            throw ApiException.conflict("DO_NOT_CALL");
        }
        if (props.renewals().enforceCallingHours()) {
            LocalTime now = LocalTime.now(clock);
            if (now.isBefore(CALLS_FROM) || !now.isBefore(CALLS_UNTIL)) {
                throw ApiException.conflict("OUTSIDE_CALLING_HOURS");
            }
        }
        Instant now = clock.instant();
        UUID id = UUID.randomUUID();
        CaseEntity c = new CaseEntity(id, CASE_TYPE, "Renewal call · " + p.getHolderName(),
                json(Map.of("policyId", p.getId())), props.pipelineVersion(), actor, now);
        c.setStatus(CaseStatus.PROCESSING);
        cases.save(c);
        calls.save(new CallEntity(id, p.getId(), now));
        audit.record(id, actor, "call.started", Map.of("policyId", p.getId(), "playbook", playbook.id(),
                "playbookVersion", playbook.version()));
        return new StartedCall(id, id, greeting(p));
    }

    // ---- tools the voice agent can call; every limit is enforced here, not in the agent ----

    private static final String TOOLS_ROLE = "hasAnyRole('VOICE','ANALYST')";
    private static final Set<String> SUMMARY_EVENTS = Set.of("tool.quote_renewal", "tool.send_payment_link",
            "rule.outside_playbook", "tool.handoff_to_human");

    @PreAuthorize(TOOLS_ROLE)
    @Transactional(readOnly = true)
    public CallView getCall(UUID callId) {
        CallEntity c = calls.findById(callId).orElseThrow(() -> callNotFound(callId));
        PolicyEntity p = policy(c);
        JsonNode transcript = readJson(c.getTranscript());
        List<SummaryItem> summary = new ArrayList<>();
        for (AuditRow row : audit.forCase(callId)) {
            if (SUMMARY_EVENTS.contains(row.action())) {
                int upTo = row.payload().path("turnIndex").asInt(0);
                summary.add(new SummaryItem(statement(row.action()), lastCustomerTurn(transcript, upTo)));
            }
        }
        return new CallView(c.getId(), c.getId(), c.getPolicyId(), p.getHolderName(), greeting(p),
                c.isIdentityVerified(), c.getVerifyFailures(), c.getOutOfPlaybookRequests(), c.isMustHandoff(),
                c.getOutcome(), c.getLastQuote() == null ? null : readJson(c.getLastQuote()), c.isPaymentLinkSent(),
                c.getHandoffReason(), c.getCallbackAt(), transcript, summary);
    }

    @PreAuthorize(TOOLS_ROLE)
    @Transactional(noRollbackFor = ApiException.class)
    public Verification verify(UUID callId, String dateOfBirth, String actor) {
        CallEntity c = openCall(callId);
        if (c.getVerifyFailures() >= playbook.maxVerifyFailures()) {
            throw ApiException.conflict("VERIFY_LOCKED");
        }
        LocalDate dob;
        try {
            dob = LocalDate.parse(dateOfBirth == null ? "" : dateOfBirth);
        } catch (DateTimeParseException e) {
            throw ApiException.badRequest("dateOfBirth must be YYYY-MM-DD");
        }
        if (c.isIdentityVerified()) {
            return new Verification(true, playbook.maxVerifyFailures() - c.getVerifyFailures(), c.isMustHandoff());
        }
        if (policy(c).getDateOfBirth().equals(dob)) {
            c.setIdentityVerified(true);
            audit.record(callId, actor, "identity.verified", Map.of("attempt", c.getVerifyFailures() + 1));
        } else {
            c.setVerifyFailures(c.getVerifyFailures() + 1);
            if (c.getVerifyFailures() >= playbook.maxVerifyFailures()) {
                c.setMustHandoff(true);
            }
            audit.record(callId, actor, "identity.failed", Map.of("attempt", c.getVerifyFailures(),
                    "mustHandoff", c.isMustHandoff()));
        }
        calls.save(c);
        return new Verification(c.isIdentityVerified(), playbook.maxVerifyFailures() - c.getVerifyFailures(),
                c.isMustHandoff());
    }

    @PreAuthorize(TOOLS_ROLE)
    @Transactional
    public PolicyView policy(UUID callId, String actor) {
        CallEntity c = verifiedCall(callId);
        PolicyEntity p = policy(c);
        audit.record(callId, actor, "tool.get_policy", Map.of("policyId", p.getId()));
        return new PolicyView(p.getId(), p.getProduct(), p.getSumInsured().longValue(), p.getExpiresOn(),
                p.getLastPremium().longValue(), p.getRenewalPremium().longValue(), readJson(p.getPremiumBreakdown()),
                readJson(p.getAddons()), p.getMobileLast4(), c.isMustHandoff());
    }

    @PreAuthorize(TOOLS_ROLE)
    @Transactional
    public Options options(UUID callId, String actor) {
        CallEntity c = verifiedCall(callId);
        List<RemovableAddon> removable = new ArrayList<>();
        if (playbook.removableOptionalAddons()) {
            for (JsonNode a : readJson(policy(c).getAddons())) {
                if (a.path("optional").asBoolean(false)) {
                    removable.add(new RemovableAddon(a.path("code").asText(), a.path("name").asText(),
                            a.path("premium").asLong()));
                }
            }
        }
        audit.record(callId, actor, "tool.list_allowed_options", Map.of("removable", removable.size()));
        return new Options(playbook.paymentPlans(), removable, playbook.maxDiscountPercent(), c.isMustHandoff());
    }

    @PreAuthorize(TOOLS_ROLE)
    @Transactional(noRollbackFor = ApiException.class)
    public Quote quote(UUID callId, QuoteRequest req, String actor) {
        CallEntity c = verifiedCall(callId);
        PolicyEntity p = policy(c);
        List<String> drop = req.dropAddons() == null ? List.of() : req.dropAddons().stream().distinct().toList();
        String plan = req.paymentPlan();
        int discount = req.discountPercent() == null ? 0 : req.discountPercent();
        if (plan == null || !playbook.paymentPlans().contains(plan) || discount < 0) {
            throw ApiException.invalidOption("INVALID_OPTION");
        }
        long annual = p.getRenewalPremium().longValue();
        for (String code : drop) {
            JsonNode addon = null;
            for (JsonNode a : readJson(p.getAddons())) {
                if (code.equals(a.path("code").asText())) {
                    addon = a;
                }
            }
            if (addon == null || !addon.path("optional").asBoolean(false) || !playbook.removableOptionalAddons()) {
                throw ApiException.invalidOption("INVALID_OPTION");
            }
            annual -= addon.path("premium").asLong();
        }
        if (discount > playbook.maxDiscountPercent()) {
            c.setOutOfPlaybookRequests(c.getOutOfPlaybookRequests() + 1);
            if (c.getOutOfPlaybookRequests() >= playbook.maxOutOfPlaybookRequests()) {
                c.setMustHandoff(true);
            }
            audit.record(callId, actor, "rule.outside_playbook", Map.of("requestedDiscountPercent", discount,
                    "maxDiscountPercent", playbook.maxDiscountPercent(), "count", c.getOutOfPlaybookRequests(),
                    "mustHandoff", c.isMustHandoff(), "turnIndex", turnCount(c)));
            calls.save(c);
            throw ApiException.invalidOption("OUTSIDE_PLAYBOOK");
        }
        annual = BigDecimal.valueOf(annual).multiply(BigDecimal.valueOf(100 - discount))
                .divide(BigDecimal.valueOf(100), 0, RoundingMode.HALF_UP).longValue();
        int instalments = "quarterly".equals(plan) ? 4 : 1;
        long per = BigDecimal.valueOf(annual).divide(BigDecimal.valueOf(instalments), 0, RoundingMode.CEILING)
                .longValue();
        UUID quoteId = UUID.randomUUID();
        Map<String, Object> stored = new LinkedHashMap<>();
        stored.put("quoteId", quoteId);
        stored.put("annualPremium", annual);
        stored.put("instalments", instalments);
        stored.put("perInstalment", per);
        stored.put("paymentPlan", plan);
        stored.put("dropAddons", drop);
        stored.put("discountPercent", discount);
        c.setLastQuote(json(stored));
        audit.record(callId, actor, "tool.quote_renewal", withTurnIndex(c, stored));
        calls.save(c);
        return new Quote(quoteId, annual, instalments, per, c.isMustHandoff());
    }

    @PreAuthorize(TOOLS_ROLE)
    @Transactional(noRollbackFor = ApiException.class)
    public PaymentLinkSent paymentLink(UUID callId, UUID quoteId, String actor) {
        CallEntity c = verifiedCall(callId);
        if (quoteId == null || c.getLastQuote() == null
                || !quoteId.toString().equals(readJson(c.getLastQuote()).path("quoteId").asText())) {
            throw ApiException.conflict("STALE_QUOTE");
        }
        c.setPaymentLinkSent(true);
        audit.record(callId, actor, "tool.send_payment_link", Map.of("quoteId", quoteId, "channel", "SMS",
                "turnIndex", turnCount(c)));
        calls.save(c);
        return new PaymentLinkSent(true, "SMS", policy(c).getMobileLast4(), c.isMustHandoff());
    }

    @PreAuthorize(TOOLS_ROLE)
    @Transactional(noRollbackFor = ApiException.class)
    public HandoffQueued handoff(UUID callId, HandoffRequest req, String actor) {
        CallEntity c = openCall(callId);
        if (req == null || req.reason() == null || req.reason().isBlank()) {
            throw ApiException.badRequest("reason is required");
        }
        c.setHandoffReason(req.reason());
        c.setCallbackAt(req.callbackAt());
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("reason", req.reason());
        payload.put("callbackAt", req.callbackAt());
        audit.record(callId, actor, "tool.handoff_to_human", withTurnIndex(c, payload));
        CaseEntity cs = cases.findById(callId).orElseThrow(() -> callNotFound(callId));
        cs.setStatus(CaseStatus.ESCALATED);
        cases.save(cs);
        calls.save(c);
        return new HandoffQueued(true, c.isMustHandoff());
    }

    @PreAuthorize(TOOLS_ROLE)
    @Transactional(noRollbackFor = ApiException.class)
    public void turn(UUID callId, TurnRequest req, String actor) {
        CallEntity c = openCall(callId);
        if (req == null || !("agent".equals(req.role()) || "customer".equals(req.role()))) {
            throw ApiException.badRequest("role must be agent or customer");
        }
        if (req.text() == null || req.text().isBlank()) {
            throw ApiException.badRequest("text is required");
        }
        ArrayNode transcript = (ArrayNode) readJson(c.getTranscript());
        ObjectNode t = transcript.addObject();
        t.put("role", req.role());
        t.put("text", req.text());
        t.put("at", req.at());
        c.setTranscript(json(transcript));
        calls.save(c);
    }

    @PreAuthorize(TOOLS_ROLE)
    @Transactional
    public CallEnded end(UUID callId, String actor) {
        CallEntity c = calls.findForUpdate(callId).orElseThrow(() -> callNotFound(callId));
        if (c.getEndedAt() != null) {
            return new CallEnded(c.getOutcome(), c.isMustHandoff());
        }
        String outcome = c.getHandoffReason() != null ? "HANDED_OFF"
                : c.isPaymentLinkSent() ? "RENEWAL_PENDING_PAYMENT" : "NO_DECISION";
        c.setOutcome(outcome);
        c.setEndedAt(clock.instant());
        CaseEntity cs = cases.findById(callId).orElseThrow(() -> callNotFound(callId));
        if (cs.getStatus() != CaseStatus.ESCALATED) {
            cs.setStatus(CaseStatus.NEEDS_REVIEW);
            cases.save(cs);
        }
        audit.record(callId, actor, "call.ended", Map.of("outcome", outcome));
        calls.save(c);
        return new CallEnded(outcome, c.isMustHandoff());
    }

    private CallEntity openCall(UUID callId) {
        CallEntity c = calls.findForUpdate(callId).orElseThrow(() -> callNotFound(callId));
        if (c.getEndedAt() != null) {
            throw ApiException.conflict("CALL_ENDED");
        }
        return c;
    }

    private CallEntity verifiedCall(UUID callId) {
        CallEntity c = openCall(callId);
        if (!c.isIdentityVerified()) {
            throw ApiException.forbidden("IDENTITY_NOT_VERIFIED");
        }
        return c;
    }

    private PolicyEntity policy(CallEntity c) {
        return policies.findById(c.getPolicyId())
                .orElseThrow(() -> ApiException.notFound("Policy " + c.getPolicyId() + " not found"));
    }

    private static ApiException callNotFound(UUID id) {
        return ApiException.notFound("Call " + id + " not found");
    }

    private String greeting(PolicyEntity p) {
        return playbook.greeting().replace("{holderName}", p.getHolderName());
    }

    private int turnCount(CallEntity c) {
        return readJson(c.getTranscript()).size();
    }

    private Map<String, Object> withTurnIndex(CallEntity c, Map<String, Object> payload) {
        Map<String, Object> m = new LinkedHashMap<>(payload);
        m.put("turnIndex", turnCount(c));
        return m;
    }

    private static String lastCustomerTurn(JsonNode transcript, int upTo) {
        for (int i = Math.min(upTo, transcript.size()) - 1; i >= 0; i--) {
            if ("customer".equals(transcript.get(i).path("role").asText())) {
                return transcript.get(i).path("text").asText();
            }
        }
        return null;
    }

    private static String statement(String action) {
        return switch (action) {
            case "tool.quote_renewal" -> "Agent quoted a renewal option within the playbook.";
            case "tool.send_payment_link" -> "Payment link sent to the customer's registered mobile.";
            case "rule.outside_playbook" -> "Customer asked for a discount beyond the playbook limit.";
            default -> "Call handed to a human colleague.";
        };
    }

    private JsonNode readJson(String s) {
        try {
            return mapper.readTree(s);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException(e);
        }
    }

    private String json(Object o) {
        try {
            return mapper.writeValueAsString(o);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException(e);
        }
    }
}
