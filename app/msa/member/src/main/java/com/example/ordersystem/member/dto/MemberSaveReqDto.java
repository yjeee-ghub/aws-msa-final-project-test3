package com.example.ordersystem.member.dto;

import com.example.ordersystem.member.domain.Member;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@NoArgsConstructor
@AllArgsConstructor
@Data
public class MemberSaveReqDto {
    private String name;
    private String loginId;
    private String nickname;
    private String email;
    private String password;

    public Member toEntity(String encodedPassword){
        return Member.builder()
                .name(this.name)
                .loginId(this.loginId)
                .nickname(this.nickname)
                .email(this.email)
                .password(encodedPassword)
                .build();
    }
}
