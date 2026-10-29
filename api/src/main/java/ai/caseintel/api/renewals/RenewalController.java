package ai.caseintel.api.renewals;

import ai.caseintel.api.renewals.RenewalDtos.QueueItem;
import ai.caseintel.api.renewals.RenewalDtos.StartCallRequest;
import ai.caseintel.api.renewals.RenewalDtos.StartedCall;
import java.security.Principal;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/renewals")
public class RenewalController {

    private final RenewalService renewals;

    public RenewalController(RenewalService renewals) {
        this.renewals = renewals;
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
}
