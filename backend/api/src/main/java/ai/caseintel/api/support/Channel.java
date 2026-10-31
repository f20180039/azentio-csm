package ai.caseintel.api.support;

public enum Channel {
    VOICE, SIM_AUDIO, TEXT;

    public static Channel parse(String value) {
        return Vocabulary.parse(Channel.class, "channel", value);
    }
}
