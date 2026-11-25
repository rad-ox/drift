package drift;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;
import org.junit.jupiter.api.extension.ExtendWith;

/** Tags a test with the contract cases it proves at one level. */
@Retention(RetentionPolicy.RUNTIME)
@Target(ElementType.METHOD)
@ExtendWith(DriftWhenExtension.class)
public @interface DriftCase {
    String contract();

    String[] cases() default {};

    String level();

    boolean strictWhen() default false;
}
