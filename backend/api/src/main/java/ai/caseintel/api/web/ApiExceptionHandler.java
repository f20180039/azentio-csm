package ai.caseintel.api.web;

import ai.caseintel.api.service.ApiException;
import ai.caseintel.api.service.RateLimitedException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.AuthenticationException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.context.request.WebRequest;
import org.springframework.web.multipart.MaxUploadSizeExceededException;
import org.springframework.web.servlet.mvc.method.annotation.ResponseEntityExceptionHandler;

@RestControllerAdvice
public class ApiExceptionHandler extends ResponseEntityExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(ApiExceptionHandler.class);

    @ExceptionHandler(ApiException.class)
    ResponseEntity<ProblemDetail> api(ApiException e) {
        ProblemDetail pd = ProblemDetail.forStatusAndDetail(e.status(), e.getMessage());
        pd.setTitle(e.title());
        HttpHeaders headers = new HttpHeaders();
        if (e instanceof RateLimitedException r) {
            headers.set(HttpHeaders.RETRY_AFTER, Long.toString(r.retryAfterSeconds()));
        }
        return ResponseEntity.status(e.status()).headers(headers).body(pd);
    }

    @ExceptionHandler(AccessDeniedException.class)
    ResponseEntity<ProblemDetail> denied(AccessDeniedException e) {
        return problem(HttpStatus.FORBIDDEN, "Forbidden", "Your role does not allow this action.");
    }

    @ExceptionHandler(AuthenticationException.class)
    ResponseEntity<ProblemDetail> unauthenticated(AuthenticationException e) {
        return problem(HttpStatus.UNAUTHORIZED, "Unauthorized", "Sign in with a valid username and password.");
    }

    @Override
    protected ResponseEntity<Object> handleMaxUploadSizeExceededException(MaxUploadSizeExceededException e,
            HttpHeaders headers, HttpStatusCode status, WebRequest request) {
        ProblemDetail pd = ProblemDetail.forStatusAndDetail(HttpStatus.PAYLOAD_TOO_LARGE,
                "Each file can be at most 20 MB, and one upload at most 100 MB.");
        pd.setTitle("File too large");
        return ResponseEntity.status(HttpStatus.PAYLOAD_TOO_LARGE).body(pd);
    }

    @ExceptionHandler(IllegalArgumentException.class)
    ResponseEntity<ProblemDetail> badArgument(IllegalArgumentException e) {
        return problem(HttpStatus.BAD_REQUEST, "Bad request", e.getMessage());
    }

    @ExceptionHandler(Exception.class)
    ResponseEntity<ProblemDetail> unexpected(Exception e) {
        log.error("Unhandled error", e);
        return problem(HttpStatus.INTERNAL_SERVER_ERROR, "Internal error",
                "Something went wrong on the server. The error has been logged.");
    }

    private static ResponseEntity<ProblemDetail> problem(HttpStatus status, String title, String detail) {
        ProblemDetail pd = ProblemDetail.forStatusAndDetail(status, detail);
        pd.setTitle(title);
        return ResponseEntity.status(status).body(pd);
    }
}
