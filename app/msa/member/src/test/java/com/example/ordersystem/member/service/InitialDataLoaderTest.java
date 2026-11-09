package com.example.ordersystem.member.service;
import com.example.ordersystem.member.domain.*;
import com.example.ordersystem.member.repository.MemberRepository;
import org.junit.jupiter.api.Test;
import org.springframework.security.crypto.password.PasswordEncoder;
import java.util.Optional;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
class InitialDataLoaderTest {
    final MemberRepository repository = mock(MemberRepository.class);
    final PasswordEncoder encoder = mock(PasswordEncoder.class);
    final String password = "test-bootstrap-password";
    @Test void createsAdminWithProvidedEmail() {
        when(encoder.encode(password)).thenReturn("encoded");
        new InitialDataLoader(repository, encoder, password, " operator@example.com ").run();
        verify(repository).save(argThat(m -> m.getEmail().equals("operator@example.com") && m.getRole() == Role.ADMIN));
    }
    @Test void updatesExistingAdminEmailWithoutChangingMatchingPassword() {
        Member admin = Member.builder().loginId("admin").role(Role.ADMIN).email("old@example.com").password("hash").build();
        when(repository.findByLoginId("admin")).thenReturn(Optional.of(admin));
        when(repository.findByEmail("new@example.com")).thenReturn(Optional.empty());
        when(encoder.matches(password, "hash")).thenReturn(true);
        new InitialDataLoader(repository, encoder, password, "new@example.com").run();
        assertEquals("new@example.com", admin.getEmail());
        assertEquals("hash", admin.getPassword());
        verify(encoder, never()).encode(anyString());
    }
    @Test void duplicateEmailStopsBeforeAdminModification() {
        when(repository.findByEmail("buyer@example.com")).thenReturn(Optional.of(Member.builder().loginId("buyer").build()));
        assertThrows(IllegalStateException.class, () -> new InitialDataLoader(repository, encoder, password, "buyer@example.com").run());
        verify(repository, never()).findByLoginId(anyString());
        verify(repository, never()).save(any());
        verifyNoInteractions(encoder);
    }
    @Test void rejectsInvalidEmailWithoutDatabaseAccess() {
        for (String email : new String[]{"", "bad", "Name <operator@example.com>", "a@b"}) {
            assertThrows(IllegalArgumentException.class, () -> new InitialDataLoader(repository, encoder, password, email).run());
        }
        verifyNoInteractions(repository);
    }
    @Test void noBootstrapPasswordLeavesAccountsUntouched() {
        new InitialDataLoader(repository, encoder, "", "").run();
        verifyNoInteractions(repository, encoder);
    }
    @Test void refusesAdminLoginOwnedByRegularMember() {
        when(repository.findByLoginId("admin")).thenReturn(Optional.of(Member.builder().loginId("admin").role(Role.USER).build()));
        assertThrows(IllegalStateException.class, () -> new InitialDataLoader(repository, encoder, password, "operator@example.com").run());
        verifyNoInteractions(encoder);
    }
}
