package ai.caseintel.api.support;

import ai.caseintel.api.audit.AuditService;
import ai.caseintel.api.config.AppProperties;
import ai.caseintel.api.domain.CaseEntity;
import ai.caseintel.api.domain.CaseStatus;
import ai.caseintel.api.renewals.CallEntity;
import ai.caseintel.api.renewals.CallRepository;
import ai.caseintel.api.repo.CaseRepository;
import ai.caseintel.api.service.ApiException;
import ai.caseintel.api.support.SupportDtos.CallDetail;
import ai.caseintel.api.support.SupportDtos.CallList;
import ai.caseintel.api.support.SupportDtos.CallSummary;
import ai.caseintel.api.support.SupportDtos.Ended;
import ai.caseintel.api.support.SupportDtos.Started;
import ai.caseintel.api.support.SupportDtos.Turn;
import ai.caseintel.api.support.SupportDtos.TurnAdded;
import ai.caseintel.api.support.SupportDtos.TurnRequest;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** Support calls reuse the calls row; turns live in its transcript jsonb as {seq, role, text, at, meta}. */
@Service
public class SupportService {

    static final String CASE_TYPE = "support_call";
    static final int MAX_LIMIT = 200;
    private static final String WRITE_ROLE = "hasRole('VOICE')";
    private static final String READ_ROLE = "hasAnyRole('ANALYST','VOICE')";

    private final CallRepository calls;
    private final CaseRepository cases;
    private final AuditService audit;
    private final Clock clock;
    private final AppProperties props;
    private final ObjectMapper mapper;

    public SupportService(CallRepository calls, CaseRepository cases, AuditService audit, Clock clock,
                          AppProperties props, ObjectMapper mapper) {
        this.calls = calls;
        this.cases = cases;
        this.audit = audit;
        this.clock = clock;
        this.props = props;
        this.mapper = mapper;
    }

    @PreAuthorize(WRITE_ROLE)
    @Transactional
    public Started start(Channel channel, String actor) {
        Instant now = clock.instant();
        UUID id = UUID.randomUUID();
        CaseEntity c = new CaseEntity(id, CASE_TYPE, "Support call · " + channel.name(),
                json(Map.of("channel", channel.name())), props.pipelineVersion(), actor, now);
        c.setStatus(CaseStatus.PROCESSING);
        cases.save(c);
        calls.save(CallEntity.support(id, channel, now));
        audit.record(id, actor, "call.started", Map.of("kind", CallKind.SUPPORT.name(), "channel", channel.name()));
        return new Started(id);
    }

    @PreAuthorize(WRITE_ROLE)
    @Transactional
    public TurnAdded addTurn(UUID callId, TurnRequest req, String actor) {
        if (req == null) {
            throw ApiException.badRequest("body is required");
        }
        TurnRole role = TurnRole.parse(req.role());
        if (req.text() == null) {
            throw ApiException.badRequest("text is required");
        }
        if (req.meta() != null && !req.meta().isNull() && !req.meta().isObject()) {
            throw ApiException.badRequest("meta must be a JSON object");
        }
        CallEntity c = lockedCall(callId);
        if (c.getEndedAt() != null) {
            throw ApiException.conflict("CALL_ENDED");
        }
        ArrayNode turns = turns(c);
        int seq = turns.size() + 1;
        ObjectNode t = turns.addObject();
        t.put("seq", seq);
        t.put("role", role.wire());
        t.put("text", req.text());
        t.put("at", req.at() == null ? clock.instant().toString() : req.at());
        t.set("meta", req.meta() != null && req.meta().isObject() ? req.meta().deepCopy() : mapper.createObjectNode());
        c.setTranscript(json(turns));
        calls.save(c);
        return new TurnAdded(seq);
    }

    /** Shallow merge: top-level keys in the patch replace those in the turn's meta. Allowed after the call ends. */
    @PreAuthorize(WRITE_ROLE)
    @Transactional
    public Turn patchMeta(UUID callId, int seq, JsonNode patch) {
        if (patch == null || !patch.isObject()) {
            throw ApiException.badRequest("meta patch must be a JSON object");
        }
        CallEntity c = lockedCall(callId);
        ArrayNode turns = turns(c);
        if (seq < 1 || seq > turns.size()) {
            throw ApiException.notFound("Turn " + seq + " not found on call " + callId);
        }
        ObjectNode t = (ObjectNode) turns.get(seq - 1);
        JsonNode existing = t.get("meta");
        ObjectNode meta = existing != null && existing.isObject() ? (ObjectNode) existing : mapper.createObjectNode();
        meta.setAll((ObjectNode) patch);
        t.set("meta", meta);
        c.setTranscript(json(turns));
        calls.save(c);
        return turn(t);
    }

    @PreAuthorize(WRITE_ROLE)
    @Transactional
    public Ended end(UUID callId, Outcome outcome, String actor) {
        CallEntity c = lockedCall(callId);
        if (c.getEndedAt() != null) {
            throw ApiException.conflict("CALL_ALREADY_ENDED");
        }
        Instant now = clock.instant();
        c.setOutcome(outcome.name());
        c.setEndedAt(now);
        calls.save(c);
        cases.findById(callId).ifPresent(cs -> {
            cs.setStatus(outcome == Outcome.ESCALATED ? CaseStatus.ESCALATED : CaseStatus.NEEDS_REVIEW);
            cases.save(cs);
        });
        audit.record(callId, actor, "call.ended", Map.of("outcome", outcome.name(), "turnCount", turns(c).size()));
        return new Ended(callId, outcome, now);
    }

    @PreAuthorize(READ_ROLE)
    @Transactional(readOnly = true)
    public CallDetail get(UUID callId) {
        CallEntity c = calls.findById(callId).filter(SupportService::isSupport)
                .orElseThrow(() -> notFound(callId));
        ArrayNode turns = turns(c);
        List<Turn> out = new ArrayList<>();
        for (JsonNode t : turns) {
            out.add(turn(t));
        }
        return new CallDetail(c.getId(), c.getChannel(), c.getStartedAt(), c.getEndedAt(), outcome(c),
                verified(turns), out);
    }

    @PreAuthorize(READ_ROLE)
    @Transactional(readOnly = true)
    public CallList list(Outcome outcome, int limit) {
        if (limit < 1 || limit > MAX_LIMIT) {
            throw ApiException.badRequest("limit must be between 1 and " + MAX_LIMIT);
        }
        PageRequest page = PageRequest.of(0, limit, Sort.by(Sort.Direction.DESC, "startedAt"));
        List<CallEntity> rows = outcome == null ? calls.findByKind(CallKind.SUPPORT, page)
                : calls.findByKindAndOutcome(CallKind.SUPPORT, outcome.name(), page);
        List<CallSummary> items = new ArrayList<>();
        for (CallEntity c : rows) {
            ArrayNode turns = turns(c);
            items.add(new CallSummary(c.getId(), c.getChannel(), c.getStartedAt(), c.getEndedAt(), outcome(c),
                    verified(turns), turns.size(), intents(turns)));
        }
        return new CallList(items);
    }

    static boolean verified(ArrayNode turns) {
        for (JsonNode t : turns) {
            if (isCustomer(t) && t.path("meta").path("verified").asBoolean(false)) {
                return true;
            }
        }
        return false;
    }

    static List<String> intents(ArrayNode turns) {
        Set<String> out = new LinkedHashSet<>();
        for (JsonNode t : turns) {
            if (isCustomer(t)) {
                for (JsonNode i : t.path("meta").path("intents")) {
                    if (i.isTextual()) {
                        out.add(i.asText());
                    }
                }
            }
        }
        return List.copyOf(out);
    }

    private static boolean isCustomer(JsonNode t) {
        return TurnRole.CUSTOMER.wire().equals(t.path("role").asText());
    }

    private static boolean isSupport(CallEntity c) {
        return c.getKind() == CallKind.SUPPORT;
    }

    private CallEntity lockedCall(UUID callId) {
        return calls.findForUpdate(callId).filter(SupportService::isSupport).orElseThrow(() -> notFound(callId));
    }

    private static Outcome outcome(CallEntity c) {
        return c.getOutcome() == null ? null : Outcome.valueOf(c.getOutcome());
    }

    private static Turn turn(JsonNode t) {
        return new Turn(t.path("seq").asInt(), t.path("role").asText(), t.path("text").asText(),
                t.path("at").isMissingNode() || t.path("at").isNull() ? null : t.path("at").asText(), t.path("meta"));
    }

    private ArrayNode turns(CallEntity c) {
        try {
            JsonNode n = mapper.readTree(c.getTranscript() == null ? "[]" : c.getTranscript());
            return n instanceof ArrayNode a ? a : mapper.createArrayNode();
        } catch (JsonProcessingException e) {
            throw new IllegalStateException(e);
        }
    }

    private static ApiException notFound(UUID id) {
        return ApiException.notFound("Support call " + id + " not found");
    }

    private String json(Object o) {
        try {
            return mapper.writeValueAsString(o);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException(e);
        }
    }
}
