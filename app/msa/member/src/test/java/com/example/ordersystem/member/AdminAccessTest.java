package com.example.ordersystem.member;

import com.example.ordersystem.member.domain.*;
import com.example.ordersystem.member.dto.*;
import com.example.ordersystem.member.repository.MemberRepository;
import com.example.ordersystem.member.service.*;
import org.junit.jupiter.api.Test;
import org.springframework.security.crypto.password.PasswordEncoder;
import java.util.Optional;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class AdminAccessTest {
    @Test void adminLoginSetsSecureCookieAndCustomerLoginClearsIt() throws Exception {
        var service = mock(MemberService.class);
        var tokens = mock(JwtTokenProvider.class);
        var controller = new com.example.ordersystem.member.controller.MemberController(service, tokens);
        var mvc = org.springframework.test.web.servlet.setup.MockMvcBuilders.standaloneSetup(controller).build();
        when(tokens.createToken("7", "ADMIN")).thenReturn("admin-token");
        when(service.login(any())).thenReturn(Member.builder().id(7L).role(Role.ADMIN).build());
        var response = mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders
                .post("/member/doLogin").contentType("application/json").content("{\"loginId\":\"admin\",\"password\":\"test\"}"))
                .andReturn().getResponse();
        assertEquals(200, response.getStatus());
        String cookie = response.getHeader("Set-Cookie");
        assertTrue(cookie.contains("ADMIN_ACCESS_TOKEN=admin-token"));
        assertTrue(cookie.contains("Secure")); assertTrue(cookie.contains("HttpOnly"));
        assertTrue(cookie.contains("SameSite=Strict"));
        when(service.login(any())).thenReturn(Member.builder().id(8L).role(Role.USER).build());
        var customer = mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders
                .post("/member/doLogin").contentType("application/json").content("{\"loginId\":\"user\",\"password\":\"test\"}"))
                .andReturn().getResponse();
        assertEquals(200, customer.getStatus());
        assertTrue(customer.getHeader("Set-Cookie").contains("Max-Age=0"));
    }

    @Test void publicSignupCannotClaimAdminIdOrRole() {
        var repository = mock(MemberRepository.class);
        var service = new MemberService(repository, mock(PasswordEncoder.class));
        assertThrows(IllegalArgumentException.class, () -> service.save(new MemberSaveReqDto("a", "ADMIN", "a", "a@b.c", "pw")));
        verifyNoInteractions(repository);
        assertEquals(Role.USER, new MemberSaveReqDto("a", "normal", "a", "a@b.c", "pw").toEntity("encoded").getRole());
    }

    @Test void existingDefaultAdminPasswordIsReplacedAndMissingSecretDisablesLogin() {
        var repository = mock(MemberRepository.class);
        var encoder = mock(PasswordEncoder.class);
        var member = Member.builder().loginId("admin").role(Role.ADMIN).password("old").build();
        when(repository.findByLoginId("admin")).thenReturn(Optional.of(member));
        when(encoder.encode("new-password-123")).thenReturn("new-hash");
        new InitialDataLoader(repository, encoder, "new-password-123", "a@b.c").run();
        assertEquals("new-hash", member.getPassword());
        var service = new MemberService(repository, encoder);
        assertThrows(IllegalArgumentException.class, () -> service.login(new LoginDto("admin", "12341234")));
    }

    @Test void bootstrapDoesNotElevateAnExistingCustomer() {
        var repository = mock(MemberRepository.class);
        when(repository.findByLoginId("admin")).thenReturn(Optional.of(Member.builder().role(Role.USER).build()));
        var loader = new InitialDataLoader(repository, mock(PasswordEncoder.class), "new-password-123", "a@b.c");
        assertThrows(IllegalStateException.class, loader::run);
        verify(repository, never()).save(any());
    }
}
