<template>
  <v-container
    fluid
    class="ace-v3-page pa-0"
  >
    <ace-v3-card
      :show-page-link="false"
      :collapse-extra-functions="false"
    />
  </v-container>
</template>

<script lang="ts">
import { Component, Vue } from 'vue-property-decorator'
import AceV3Card from '@/components/widgets/ace-v3/AceV3Card.vue'

@Component({
  components: {
    AceV3Card
  }
})
export default class AcePro extends Vue {}
</script>

<style lang="scss" scoped>
.ace-v3-page {
  box-sizing: border-box;
  width: 100%;
  max-width: 100%;
  min-width: 0;
}
</style>
