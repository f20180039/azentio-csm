package ai.caseintel.api.renewals;

import ai.caseintel.api.support.CallKind;
import ai.caseintel.api.support.Channel;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;
import java.util.UUID;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

@Entity
@Table(name = "calls")
public class CallEntity {

    @Id
    private UUID id;

    @Column(name = "policy_id")
    private String policyId;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private CallKind kind = CallKind.RENEWAL;

    @Enumerated(EnumType.STRING)
    private Channel channel;

    @Column(name = "started_at", nullable = false)
    private Instant startedAt;

    @Column(name = "ended_at")
    private Instant endedAt;

    @Column(name = "identity_verified", nullable = false)
    private boolean identityVerified;

    @Column(name = "verify_failures", nullable = false)
    private int verifyFailures;

    @Column(name = "out_of_playbook_requests", nullable = false)
    private int outOfPlaybookRequests;

    @Column(name = "must_handoff", nullable = false)
    private boolean mustHandoff;

    private String outcome;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "last_quote", columnDefinition = "jsonb")
    private String lastQuote;

    @Column(name = "payment_link_sent", nullable = false)
    private boolean paymentLinkSent;

    @Column(name = "handoff_reason")
    private String handoffReason;

    @Column(name = "callback_at")
    private String callbackAt;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(nullable = false, columnDefinition = "jsonb")
    private String transcript = "[]";

    protected CallEntity() {}

    public CallEntity(UUID id, String policyId, Instant startedAt) {
        this.id = id;
        this.policyId = policyId;
        this.startedAt = startedAt;
    }

    public static CallEntity support(UUID id, Channel channel, Instant startedAt) {
        CallEntity c = new CallEntity(id, null, startedAt);
        c.kind = CallKind.SUPPORT;
        c.channel = channel;
        return c;
    }

    public UUID getId() { return id; }
    public String getPolicyId() { return policyId; }
    public CallKind getKind() { return kind; }
    public Channel getChannel() { return channel; }
    public Instant getStartedAt() { return startedAt; }
    public Instant getEndedAt() { return endedAt; }
    public boolean isIdentityVerified() { return identityVerified; }
    public int getVerifyFailures() { return verifyFailures; }
    public int getOutOfPlaybookRequests() { return outOfPlaybookRequests; }
    public boolean isMustHandoff() { return mustHandoff; }
    public String getOutcome() { return outcome; }
    public String getLastQuote() { return lastQuote; }
    public boolean isPaymentLinkSent() { return paymentLinkSent; }
    public String getHandoffReason() { return handoffReason; }
    public String getCallbackAt() { return callbackAt; }
    public String getTranscript() { return transcript; }

    public void setEndedAt(Instant endedAt) { this.endedAt = endedAt; }
    public void setIdentityVerified(boolean identityVerified) { this.identityVerified = identityVerified; }
    public void setVerifyFailures(int verifyFailures) { this.verifyFailures = verifyFailures; }
    public void setOutOfPlaybookRequests(int n) { this.outOfPlaybookRequests = n; }
    public void setMustHandoff(boolean mustHandoff) { this.mustHandoff = mustHandoff; }
    public void setOutcome(String outcome) { this.outcome = outcome; }
    public void setLastQuote(String lastQuote) { this.lastQuote = lastQuote; }
    public void setPaymentLinkSent(boolean paymentLinkSent) { this.paymentLinkSent = paymentLinkSent; }
    public void setHandoffReason(String handoffReason) { this.handoffReason = handoffReason; }
    public void setCallbackAt(String callbackAt) { this.callbackAt = callbackAt; }
    public void setTranscript(String transcript) { this.transcript = transcript; }
}
