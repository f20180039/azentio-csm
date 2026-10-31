package ai.caseintel.api.support;

import ai.caseintel.api.support.SupportDtos.CallDetail;
import ai.caseintel.api.support.SupportDtos.CallList;
import ai.caseintel.api.support.SupportDtos.EndRequest;
import ai.caseintel.api.support.SupportDtos.Ended;
import ai.caseintel.api.support.SupportDtos.StartRequest;
import ai.caseintel.api.support.SupportDtos.Started;
import ai.caseintel.api.support.SupportDtos.Turn;
import ai.caseintel.api.support.SupportDtos.TurnAdded;
import ai.caseintel.api.support.SupportDtos.TurnRequest;
import com.fasterxml.jackson.databind.JsonNode;
import java.security.Principal;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/support/calls")
public class SupportController {

    private final SupportService support;

    public SupportController(SupportService support) {
        this.support = support;
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public Started start(@RequestBody(required = false) StartRequest body, Principal principal) {
        return support.start(Channel.parse(body == null ? null : body.channel()), principal.getName());
    }

    @PostMapping("/{id}/turns")
    @ResponseStatus(HttpStatus.CREATED)
    public TurnAdded turn(@PathVariable UUID id, @RequestBody TurnRequest body, Principal principal) {
        return support.addTurn(id, body, principal.getName());
    }

    @PatchMapping("/{id}/turns/{seq}/meta")
    public Turn patchMeta(@PathVariable UUID id, @PathVariable int seq, @RequestBody JsonNode body) {
        return support.patchMeta(id, seq, body);
    }

    @PostMapping("/{id}/end")
    public Ended end(@PathVariable UUID id, @RequestBody(required = false) EndRequest body, Principal principal) {
        return support.end(id, Outcome.parse(body == null ? null : body.outcome()), principal.getName());
    }

    @GetMapping("/{id}")
    public CallDetail get(@PathVariable UUID id) {
        return support.get(id);
    }

    @GetMapping
    public CallList list(@RequestParam(required = false) String outcome,
                         @RequestParam(defaultValue = "50") int limit) {
        return support.list(outcome == null || outcome.isBlank() ? null : Outcome.parse(outcome), limit);
    }
}
