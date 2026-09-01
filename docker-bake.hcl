variable "WHEEL_PATH" {
  default = ""
}

variable "WHEEL_SHA256" {
  default = ""
}

variable "VERSION" {
  default = ""
}

variable "REVISION" {
  default = ""
}

variable "LABELS_JSON" {
  default = "{}"
}

variable "TAGS" {
  type    = list(string)
  default = ["traefik-certificate-exporter:local"]
}

variable "PLATFORMS" {
  type    = list(string)
  default = []
}

variable "OUTPUTS" {
  type    = list(string)
  default = ["type=docker"]
}

variable "ATTESTATIONS" {
  type    = list(string)
  default = []
}

group "default" {
  targets = ["image"]
}

target "image" {
  context    = "."
  dockerfile = "docker/Dockerfile"
  target     = "runtime"

  args = {
    BASE_IMAGE    = "ghcr.io/linuxserver/baseimage-alpine:3.24@sha256:e17494fc7ec17c64f1b502d52705aa99d7a1cd8ccf59bb7b36003db89d97d2c6"
    POETRY_VERSION = "2.4.2"
    WHEEL_PATH     = WHEEL_PATH
    WHEEL_SHA256   = WHEEL_SHA256
    VERSION        = VERSION
    REVISION       = REVISION
  }

  labels = merge({
    "org.opencontainers.image.title"       = "traefik-certificate-exporter"
    "org.opencontainers.image.description" = "Export certificates from Traefik's ACME store"
    "org.opencontainers.image.source"      = "https://github.com/ravensorb/traefik-certificate-exporter"
  }, jsondecode(LABELS_JSON), {
    "org.opencontainers.image.version"     = VERSION
    "org.opencontainers.image.revision"    = REVISION
  })

  tags      = TAGS
  platforms = PLATFORMS
  output    = OUTPUTS
  attest    = ATTESTATIONS
}
