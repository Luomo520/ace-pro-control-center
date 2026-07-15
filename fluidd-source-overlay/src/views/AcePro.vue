<template>
  <v-container
    fluid
    class="pa-0"
  >
    <ace-pro-card :show-page-link="false" />
  </v-container>
</template>

<script lang="ts">
import { Component, Vue } from 'vue-property-decorator'
import AceProCard from '@/components/widgets/acepro/AceProCard.vue'

@Component({
  components: {
    AceProCard,
  },
})
export default class AcePro extends Vue {}
</script>
