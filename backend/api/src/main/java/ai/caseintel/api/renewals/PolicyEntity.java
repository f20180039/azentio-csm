package ai.caseintel.api.renewals;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.math.BigDecimal;
import java.time.LocalDate;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

@Entity
@Table(name = "policies")
public class PolicyEntity {

    @Id
    private String id;

    @Column(name = "holder_name", nullable = false)
    private String holderName;

    @Column(name = "date_of_birth", nullable = false)
    private LocalDate dateOfBirth;

    @JdbcTypeCode(SqlTypes.CHAR)
    @Column(name = "mobile_last4", nullable = false, length = 4)
    private String mobileLast4;

    @Column(nullable = false)
    private String product;

    @Column(name = "sum_insured", nullable = false, precision = 12, scale = 0)
    private BigDecimal sumInsured;

    @Column(name = "expires_on", nullable = false)
    private LocalDate expiresOn;

    @Column(name = "last_premium", nullable = false, precision = 12, scale = 0)
    private BigDecimal lastPremium;

    @Column(name = "renewal_premium", nullable = false, precision = 12, scale = 0)
    private BigDecimal renewalPremium;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "premium_breakdown", nullable = false, columnDefinition = "jsonb")
    private String premiumBreakdown = "[]";

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(nullable = false, columnDefinition = "jsonb")
    private String addons = "[]";

    @Column(name = "claim_rejected_12m", nullable = false)
    private boolean claimRejected12m;

    @Column(name = "open_complaint", nullable = false)
    private boolean openComplaint;

    @Column(name = "autodebit_failed", nullable = false)
    private boolean autodebitFailed;

    @Column(name = "reminders_ignored", nullable = false)
    private int remindersIgnored;

    @Column(name = "do_not_call", nullable = false)
    private boolean doNotCall;

    protected PolicyEntity() {}

    public String getId() { return id; }
    public String getHolderName() { return holderName; }
    public LocalDate getDateOfBirth() { return dateOfBirth; }
    public String getMobileLast4() { return mobileLast4; }
    public String getProduct() { return product; }
    public BigDecimal getSumInsured() { return sumInsured; }
    public LocalDate getExpiresOn() { return expiresOn; }
    public BigDecimal getLastPremium() { return lastPremium; }
    public BigDecimal getRenewalPremium() { return renewalPremium; }
    public String getPremiumBreakdown() { return premiumBreakdown; }
    public String getAddons() { return addons; }
    public boolean isClaimRejected12m() { return claimRejected12m; }
    public boolean isOpenComplaint() { return openComplaint; }
    public boolean isAutodebitFailed() { return autodebitFailed; }
    public int getRemindersIgnored() { return remindersIgnored; }
    public boolean isDoNotCall() { return doNotCall; }
}
