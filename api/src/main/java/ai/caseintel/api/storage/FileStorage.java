package ai.caseintel.api.storage;

import ai.caseintel.api.config.AppProperties;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import org.springframework.stereotype.Component;

/** Content-addressed store: a file lives at {@code <dir>/<sha256>}, so identical uploads share one copy. */
@Component
public class FileStorage {

    private final Path root;

    public FileStorage(AppProperties props) {
        this.root = Path.of(props.storage().dir()).toAbsolutePath().normalize();
        try {
            Files.createDirectories(root);
        } catch (IOException e) {
            throw new UncheckedIOException("Cannot create storage dir " + root, e);
        }
    }

    public static String sha256(byte[] bytes) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

    public Path store(String sha256, byte[] bytes) {
        Path target = root.resolve(sha256);
        if (Files.exists(target)) {
            return target;
        }
        try {
            Path tmp = Files.createTempFile(root, sha256, ".part");
            Files.write(tmp, bytes);
            Files.move(tmp, target, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
            return target;
        } catch (IOException e) {
            throw new UncheckedIOException("Cannot store " + sha256, e);
        }
    }

    public Path resolve(String storagePath) {
        return Path.of(storagePath);
    }
}
