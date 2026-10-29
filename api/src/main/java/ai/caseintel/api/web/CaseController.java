package ai.caseintel.api.web;

import ai.caseintel.api.domain.CaseStatus;
import ai.caseintel.api.service.CaseService;
import ai.caseintel.api.service.Dtos;
import java.net.URI;
import java.security.Principal;
import java.util.List;
import java.util.UUID;
import org.springframework.data.domain.Page;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RequestPart;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

@RestController
@RequestMapping("/api/v1/cases")
public class CaseController {

    private final CaseService cases;

    public CaseController(CaseService cases) {
        this.cases = cases;
    }

    @PostMapping(consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<Dtos.CaseDetail> upload(@RequestParam String caseType,
                                                  @RequestParam(required = false) String title,
                                                  @RequestParam(required = false) String attributes,
                                                  @RequestPart("files") List<MultipartFile> files,
                                                  Principal principal) {
        Dtos.UploadResult r = cases.upload(caseType, title, attributes, files, principal.getName());
        return ResponseEntity.status(r.cacheHit() ? HttpStatus.OK : HttpStatus.CREATED)
                .location(URI.create("/api/v1/cases/" + r.detail().id()))
                .header("X-Cache", r.cacheHit() ? "HIT" : "MISS")
                .body(r.detail());
    }

    @GetMapping
    public Page<Dtos.CaseSummary> list(@RequestParam(required = false) CaseStatus status,
                                       @RequestParam(required = false) String caseType,
                                       @RequestParam(defaultValue = "0") int page,
                                       @RequestParam(defaultValue = "20") int size) {
        return cases.list(status, caseType, page, size);
    }

    @GetMapping("/{id}")
    public Dtos.CaseDetail get(@PathVariable UUID id) {
        return cases.get(id);
    }

    @GetMapping("/{id}/documents/{docId}/pages")
    public List<Dtos.PageView> pages(@PathVariable UUID id, @PathVariable UUID docId) {
        return cases.pages(id, docId);
    }

    @PostMapping("/{id}/findings/{fid}/decision")
    public Dtos.CaseDetail decideFinding(@PathVariable UUID id, @PathVariable UUID fid,
                                         @RequestBody Dtos.FindingDecision body, Principal principal) {
        return cases.decideFinding(id, fid, body, principal.getName());
    }

    @PostMapping("/{id}/decision")
    public Dtos.CaseDetail decideCase(@PathVariable UUID id, @RequestBody Dtos.CaseDecision body,
                                      Principal principal) {
        return cases.decideCase(id, body, principal.getName());
    }

    @GetMapping("/{id}/audit")
    public List<Dtos.AuditView> audit(@PathVariable UUID id) {
        return cases.audit(id);
    }
}
