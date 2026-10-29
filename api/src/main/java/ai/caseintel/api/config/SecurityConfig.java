package ai.caseintel.api.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletResponse;
import java.util.List;
import java.util.Map;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.security.config.Customizer;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.core.userdetails.User;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.crypto.factory.PasswordEncoderFactories;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.provisioning.InMemoryUserDetailsManager;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;

@Configuration
@EnableMethodSecurity
public class SecurityConfig {

    @Bean
    SecurityFilterChain securityFilterChain(HttpSecurity http, ObjectMapper mapper) throws Exception {
        return http
                .csrf(AbstractHttpConfigurer::disable)
                .cors(Customizer.withDefaults())
                .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(auth -> auth
                        .requestMatchers(HttpMethod.OPTIONS, "/**").permitAll()
                        .requestMatchers("/api/v1/health", "/actuator/health/**", "/swagger-ui.html",
                                "/swagger-ui/**", "/v3/api-docs/**").permitAll()
                        .anyRequest().authenticated())
                .httpBasic(basic -> basic.authenticationEntryPoint((req, res, ex) ->
                        writeProblem(mapper, res, HttpServletResponse.SC_UNAUTHORIZED, "Unauthorized",
                                "Sign in with a valid username and password.")))
                .exceptionHandling(ex -> ex.accessDeniedHandler((req, res, e) ->
                        writeProblem(mapper, res, HttpServletResponse.SC_FORBIDDEN, "Forbidden",
                                "Your role does not allow this action.")))
                .build();
    }

    // Basic auth without WWW-Authenticate keeps the browser from showing its native login dialog.
    private static void writeProblem(ObjectMapper mapper, HttpServletResponse res, int status, String title,
                                     String detail) throws java.io.IOException {
        res.setStatus(status);
        res.setContentType(MediaType.APPLICATION_PROBLEM_JSON_VALUE);
        mapper.writeValue(res.getOutputStream(),
                Map.of("type", "about:blank", "title", title, "status", status, "detail", detail));
    }

    @Bean
    PasswordEncoder passwordEncoder() {
        return PasswordEncoderFactories.createDelegatingPasswordEncoder();
    }

    @Bean
    UserDetailsService users(PasswordEncoder encoder) {
        return new InMemoryUserDetailsManager(
                User.withUsername("analyst").password(encoder.encode("analyst")).roles("ANALYST").build(),
                User.withUsername("reviewer").password(encoder.encode("reviewer")).roles("REVIEWER", "ANALYST").build(),
                User.withUsername("admin").password(encoder.encode("admin")).roles("ADMIN", "REVIEWER", "ANALYST").build());
    }

    @Bean
    CorsConfigurationSource corsConfigurationSource(AppProperties props) {
        CorsConfiguration cors = new CorsConfiguration();
        cors.setAllowedOrigins(props.cors().allowedOrigins());
        cors.setAllowedMethods(List.of("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"));
        cors.setAllowedHeaders(List.of("Authorization", "Content-Type"));
        cors.setExposedHeaders(List.of("X-Cache", "Retry-After", "Location"));
        cors.setAllowCredentials(true);
        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", cors);
        return source;
    }
}
