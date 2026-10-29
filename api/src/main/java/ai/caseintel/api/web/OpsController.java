package ai.caseintel.api.web;

import ai.caseintel.api.audit.AuditChain;
import ai.caseintel.api.service.Dtos;
import ai.caseintel.api.service.OpsService;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1")
public class OpsController {

    private final OpsService ops;

    public OpsController(OpsService ops) {
        this.ops = ops;
    }

    @GetMapping("/packs")
    public List<Dtos.PackView> packs() {
        return ops.packs();
    }

    @GetMapping("/stats")
    public Dtos.Stats stats() {
        return ops.stats();
    }

    @GetMapping("/audit/verify")
    public AuditChain.Verification verifyAudit() {
        return ops.verifyAudit();
    }

    @GetMapping("/me")
    public Dtos.Me me(Authentication auth) {
        return new Dtos.Me(auth.getName(), auth.getAuthorities().stream()
                .map(GrantedAuthority::getAuthority)
                .map(a -> a.startsWith("ROLE_") ? a.substring(5) : a)
                .sorted()
                .toList());
    }

    @GetMapping("/health")
    public ResponseEntity<Dtos.Health> health() {
        Dtos.Health h = ops.health();
        return ResponseEntity.status("DOWN".equals(h.db()) ? HttpStatus.SERVICE_UNAVAILABLE : HttpStatus.OK).body(h);
    }
}
