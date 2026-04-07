# core/serializers.py

from rest_framework import serializers
from .models import Student
from rest_framework_simplejwt.tokens import RefreshToken


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model  = Student
        fields = [
            'student_id',
            'full_name',
            'department',
            'year_of_study',
            'phone',
            'age',
            'gender',
            'password',
        ]
        extra_kwargs = {
            'age':    {'required': True},
            'gender': {'required': True},
            'phone':  {'required': False, 'allow_blank': True, 'allow_null': True},
        }

    def validate_student_id(self, value):
        import re
        if not re.match(r'^ISL-\d{4}$', value.strip()):
            raise serializers.ValidationError(
                'Student ID must match format ISL-XXXX (e.g. ISL-1234).'
            )
        return value.strip()

    def validate_full_name(self, value):
        if not value or len(value.strip()) < 3:
            raise serializers.ValidationError(
                'Full name must be at least 3 characters.'
            )
        return value.strip()

    def validate_department(self, value):
        from .models import Student as S
        valid = {d[0] for d in S.DEPARTMENTS}
        if value not in valid:
            raise serializers.ValidationError(
                f'Invalid department. Must be one of: {", ".join(sorted(valid))}.'
            )
        return value

    def validate_year_of_study(self, value):
        from .models import Student as S
        valid = {y[0] for y in S.YEARS}
        if value not in valid:
            raise serializers.ValidationError(
                f'Invalid year of study. Must be one of: {", ".join(sorted(valid))}.'
            )
        return value

    def validate_age(self, value):
        if value is None:
            raise serializers.ValidationError('Age is required.')
        if not (18 <= value <= 35):
            raise serializers.ValidationError(
                'Age must be between 18 and 35.'
            )
        return value

    def validate_gender(self, value):
        
        if not value:
            raise serializers.ValidationError(
                'Gender is required. Must be "male" or "female".'
            )
        normalised = value.strip().lower()
        if normalised not in {'male', 'female'}:
            raise serializers.ValidationError(
                'Gender must be "male" or "female".'
            )
        return normalised

    def validate_password(self, value):
        if len(value) < 8:
            raise serializers.ValidationError(
                'Password must be at least 8 characters.'
            )
        return value

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = Student.objects.create_user(password=password, **validated_data)
        return user


class LoginSerializer(serializers.Serializer):
    student_id = serializers.CharField()
    password   = serializers.CharField()

    def validate(self, data):
        from django.contrib.auth import authenticate

        user = authenticate(
            username=data['student_id'],
            password=data['password'],
        )

        if not user:
            raise serializers.ValidationError('Invalid credentials.')

        refresh = RefreshToken.for_user(user)

        return {
            'refresh': str(refresh),
            'access':  str(refresh.access_token),
        }