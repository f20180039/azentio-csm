package ai.caseintel.api.support;

import ai.caseintel.api.service.ApiException;
import java.util.Arrays;
import java.util.stream.Collectors;

final class Vocabulary {

    private Vocabulary() {}

    static <E extends Enum<E>> E parse(Class<E> type, String field, String value) {
        if (value != null) {
            for (E e : type.getEnumConstants()) {
                if (e.name().equals(value)) {
                    return e;
                }
            }
        }
        throw ApiException.badRequest(field + " must be one of " + Arrays.stream(type.getEnumConstants())
                .map(Enum::name).collect(Collectors.joining(", ")) + (value == null ? "" : "; got '" + value + "'"));
    }
}
