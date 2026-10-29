package ai.caseintel.api.renewals;

import ai.caseintel.api.renewals.RenewalDtos.CallEnded;
import ai.caseintel.api.renewals.RenewalDtos.CallView;
import ai.caseintel.api.renewals.RenewalDtos.HandoffQueued;
import ai.caseintel.api.renewals.RenewalDtos.HandoffRequest;
import ai.caseintel.api.renewals.RenewalDtos.Dashboard;
import ai.caseintel.api.renewals.RenewalDtos.Options;
import ai.caseintel.api.renewals.RenewalDtos.PaymentLinkRequest;
import ai.caseintel.api.renewals.RenewalDtos.PaymentLinkSent;
import ai.caseintel.api.renewals.RenewalDtos.PolicyView;
import ai.caseintel.api.renewals.RenewalDtos.Quote;
import ai.caseintel.api.renewals.RenewalDtos.QuoteRequest;
import ai.caseintel.api.renewals.RenewalDtos.TurnRequest;
import ai.caseintel.api.renewals.RenewalDtos.Verification;
import ai.caseintel.api.renewals.RenewalDtos.VerifyRequest;
import ai.caseintel.api.renewals.RenewalDtos.QueueItem;
import ai.caseintel.api.renewals.RenewalDtos.StartCallRequest;
import ai.caseintel.api.renewals.RenewalDtos.StartedCall;
import java.security.Principal;
import java.util.List;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/renewals")
public class RenewalController {

    private final RenewalService renewals;
    private final DashboardService dashboard;

    public RenewalController(RenewalService renewals, DashboardService dashboard) {
        this.renewals = renewals;
        this.dashboard = dashboard;
    }

    @GetMapping("/dashboard")
    public Dashboard dashboard() {
        return dashboard.dashboard();
    }

    @GetMapping("/queue")
    public List<QueueItem> queue() {
        return renewals.queue();
    }

    @PostMapping("/calls")
    @ResponseStatus(HttpStatus.CREATED)
    public StartedCall startCall(@RequestBody StartCallRequest body, Principal principal) {
        return renewals.startCall(body.policyId(), principal.getName());
    }

    @GetMapping("/calls/{callId}")
    public CallView call(@PathVariable UUID callId) {
        return renewals.getCall(callId);
    }

    @PostMapping("/calls/{callId}/verify")
    public Verification verify(@PathVariable UUID callId, @RequestBody VerifyRequest body, Principal principal) {
        return renewals.verify(callId, body.dateOfBirth(), principal.getName());
    }

    @GetMapping("/calls/{callId}/policy")
    public PolicyView policy(@PathVariable UUID callId, Principal principal) {
        return renewals.policy(callId, principal.getName());
    }

    @GetMapping("/calls/{callId}/options")
    public Options options(@PathVariable UUID callId, Principal principal) {
        return renewals.options(callId, principal.getName());
    }

    @PostMapping("/calls/{callId}/quote")
    public Quote quote(@PathVariable UUID callId, @RequestBody QuoteRequest body, Principal principal) {
        return renewals.quote(callId, body, principal.getName());
    }

    @PostMapping("/calls/{callId}/payment-link")
    public PaymentLinkSent paymentLink(@PathVariable UUID callId, @RequestBody PaymentLinkRequest body,
                                       Principal principal) {
        return renewals.paymentLink(callId, body.quoteId(), principal.getName());
    }

    @PostMapping("/calls/{callId}/handoff")
    public HandoffQueued handoff(@PathVariable UUID callId, @RequestBody HandoffRequest body, Principal principal) {
        return renewals.handoff(callId, body, principal.getName());
    }

    @PostMapping("/calls/{callId}/turns")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void turn(@PathVariable UUID callId, @RequestBody TurnRequest body, Principal principal) {
        renewals.turn(callId, body, principal.getName());
    }

    @PostMapping("/calls/{callId}/end")
    public CallEnded end(@PathVariable UUID callId, Principal principal) {
        return renewals.end(callId, principal.getName());
    }
}
